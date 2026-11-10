use pyo3::{exceptions::PyValueError, prelude::*};
use serde_json::{json, Value};
use std::collections::{HashMap, VecDeque};

type Vec3 = [f64; 3];
type Sample = [f64; 4];
type Spine = (i64, Option<i64>, Vec<Sample>);
type Bone = (i64, Option<i64>, Vec3, Vec3, f64);
type Export = (String, usize, usize);

const EPS: f64 = 1e-6;

struct Branch {
    id: i64,
    parent: Option<i64>,
    samples: Vec<Sample>,
    parent_segment: Option<usize>,
}

#[derive(Clone, Copy)]
struct Attachment {
    child: usize,
    segment: usize,
    t: f64,
}

struct Hierarchy {
    order: Vec<usize>,
    children: Vec<Vec<usize>>,
    parents: Vec<Option<usize>>,
}

fn xyz(s: Sample) -> Vec3 {
    [s[0], s[1], s[2]]
}

fn sub(a: Vec3, b: Vec3) -> Vec3 {
    std::array::from_fn(|i| a[i] - b[i])
}

fn dot(a: Vec3, b: Vec3) -> f64 {
    a.into_iter().zip(b).map(|(a, b)| a * b).sum()
}

fn length(v: Vec3) -> f64 {
    dot(v, v).sqrt()
}

fn cross(a: Vec3, b: Vec3) -> Vec3 {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

fn unit(v: Vec3) -> Vec3 {
    let n = length(v);
    v.map(|v| v / n)
}

fn sample(p: Vec3, radius: f64) -> Sample {
    [p[0], p[1], p[2], radius]
}

fn lerp(a: Sample, b: Sample, t: f64) -> Sample {
    std::array::from_fn(|i| a[i] + (b[i] - a[i]) * t)
}

fn topology(rows: &[(i64, Option<i64>)]) -> Result<Hierarchy, String> {
    let ids: HashMap<_, _> = rows.iter().enumerate().map(|(i, row)| (row.0, i)).collect();
    if ids.len() != rows.len() {
        return Err("duplicate source IDs".into());
    }
    let mut children = vec![Vec::new(); rows.len()];
    let mut parents = vec![None; rows.len()];
    let mut pending = VecDeque::new();
    for (index, &(id, parent)) in rows.iter().enumerate() {
        if let Some(parent) = parent {
            let &p = ids
                .get(&parent)
                .ok_or_else(|| format!("source {id}: missing parent {parent}"))?;
            children[p].push(index);
            parents[index] = Some(p);
        } else {
            pending.push_back(index);
        }
    }
    if pending.is_empty() {
        return Err("no root in source hierarchy".into());
    }
    let mut order = Vec::with_capacity(rows.len());
    while let Some(i) = pending.pop_front() {
        order.push(i);
        pending.extend(children[i].iter().copied());
    }
    if order.len() != rows.len() {
        return Err("cycle in source hierarchy".into());
    }
    Ok(Hierarchy {
        order,
        children,
        parents,
    })
}

fn bone_branches(bones: Vec<Bone>) -> Result<Vec<Branch>, String> {
    let rows: Vec<_> = bones.iter().map(|b| (b.0, b.1)).collect();
    let Hierarchy {
        order,
        children,
        parents,
    } = topology(&rows)?;
    let mut owners = vec![None; bones.len()];
    let mut segments = vec![0; bones.len()];
    let mut branches: Vec<Branch> = Vec::new();

    for i in order {
        let (id, _, start, end, radius) = bones[i];
        if length(sub(end, start)) <= EPS || !radius.is_finite() || radius <= 0.0 {
            return Err(format!("bone {id}: invalid physical segment or radius"));
        }
        let parent_index = parents[i];
        // A physical continuation starts at the parent tip. Offset children join its segment.
        let continued = parent_index.filter(|&p| {
            children[p]
                .iter()
                .find(|&&child| length(sub(bones[child].2, bones[p].3)) <= EPS)
                == Some(&i)
        });
        let branch_index = if let Some(p) = continued {
            owners[p].ok_or("continuation has no parent branch")?
        } else {
            let owner = parent_index.and_then(|p| owners[p]);
            let parent_id = owner.map(|p: usize| branches[p].id);
            branches.push(Branch {
                id,
                parent: parent_id,
                samples: Vec::new(),
                parent_segment: parent_index.map(|p| segments[p]),
            });
            branches.len() - 1
        };
        let samples = &mut branches[branch_index].samples;
        let first = sample(start, radius);
        if continued.is_some() {
            *samples.last_mut().ok_or("missing parent tip")? = first;
        } else {
            samples.push(first);
        }
        segments[i] = samples.len() - 1;
        samples.push(sample(end, radius));
        owners[i] = Some(branch_index);
    }
    Ok(branches)
}

fn attachments(
    branches: &[Branch],
    children: &[Vec<usize>],
) -> Result<Vec<Vec<Attachment>>, String> {
    let mut result = vec![Vec::new(); branches.len()];
    for (i, branch) in branches.iter().enumerate() {
        if branch.samples.len() < 2
            || branch.samples.iter().any(|p| {
                !p.iter()
                    .all(|v| v.is_finite() && v.abs() < f32::MAX as f64 / 100.0)
                    || p[3] <= 0.0
            })
            || branch
                .samples
                .windows(2)
                .any(|w| length(sub(xyz(w[1]), xyz(w[0]))) <= EPS)
        {
            return Err(format!(
                "branch {}: needs distinct finite points and positive radii",
                branch.id
            ));
        }
        for &child in &children[i] {
            let other = &branches[child];
            let start = xyz(*other
                .samples
                .first()
                .ok_or_else(|| format!("branch {}: no points", other.id))?);
            let best = branch
                .samples
                .windows(2)
                .enumerate()
                .filter(|(segment, _)| other.parent_segment.is_none_or(|s| s == *segment))
                .filter_map(|(segment, w)| {
                    let a = xyz(w[0]);
                    let d = sub(xyz(w[1]), a);
                    let span = length(d);
                    let t = (dot(sub(start, a), d) / dot(d, d)).clamp(0.0, 1.0);
                    let t = if t * span <= EPS {
                        0.0
                    } else if (1.0 - t) * span <= EPS {
                        1.0
                    } else {
                        t
                    };
                    let distance = length(sub(start, xyz(lerp(w[0], w[1], t))));
                    distance
                        .is_finite()
                        .then_some((distance, Attachment { child, segment, t }))
                })
                .min_by(|a, b| a.0.total_cmp(&b.0));
            let (_, attachment) = best.ok_or_else(|| {
                format!(
                    "branch {}: no usable segment on parent {}",
                    other.id, branch.id
                )
            })?;
            result[i].push(attachment);
        }
        result[i].sort_by(|a, b| a.segment.cmp(&b.segment).then(a.t.total_cmp(&b.t)));
    }
    Ok(result)
}

fn push_point(samples: &mut Vec<Sample>, line: &mut Vec<usize>, point: Sample) -> usize {
    let index = samples.len();
    line.push(index);
    samples.push(point);
    index
}

fn direction_row(tangent: Vec3) -> Vec<f64> {
    // The UE JSON reader swaps Y and Z, so construct the frame in UE space.
    let swap = |[x, y, z]: [f64; 3]| [x, z, y];
    let apical = swap(tangent);
    let reference = if apical[0].abs() < 0.99 {
        [1., 0., 0.]
    } else {
        [0., 1., 0.]
    };
    let up = unit(cross(apical, reference));
    let axillary = cross(up, apical);
    [tangent, swap(axillary), [0.; 3], [0.; 3], [0.; 3], swap(up)].concat()
}

fn encode(branches: Vec<Branch>) -> Result<Export, String> {
    let rows: Vec<_> = branches.iter().map(|b| (b.id, b.parent)).collect();
    let Hierarchy {
        order,
        children,
        parents: parent_indices,
    } = topology(&rows)?;
    let attachments = attachments(&branches, &children)?;
    let n = branches.len();
    let mut junctions = vec![None; n];
    let mut lines = vec![Vec::new(); n];
    let mut samples = Vec::new();
    let mut generations = vec![1; n];
    let mut plants = vec![0; n];
    let mut parents = vec![vec![0]; n];
    let mut next_plant = 0;

    for &i in &order {
        let b = &branches[i];
        let line = &mut lines[i];
        let start = b.samples[0];
        let start_index = if let Some(junction) = junctions[i] {
            line.push(junction);
            let anchor = samples[junction];
            let offset = sub(xyz(start), xyz(anchor));
            let distance = length(offset);
            if distance > EPS {
                if distance > 4.0 * EPS {
                    let next = unit(sub(xyz(b.samples[1]), xyz(start)));
                    // One Hermite midpoint bends the connector toward the original branch tangent.
                    let midpoint = std::array::from_fn(|k| {
                        (anchor[k] + start[k]) * 0.5 + (offset[k] - next[k] * distance) * 0.125
                    });
                    push_point(&mut samples, line, sample(midpoint, start[3]));
                }
                push_point(&mut samples, line, start)
            } else {
                junction
            }
        } else {
            next_plant += 1;
            plants[i] = next_plant;
            push_point(&mut samples, line, start)
        };
        for &child in &children[i] {
            parents[child] = parents[i].iter().copied().chain([i + 1]).collect();
            generations[child] = generations[i] + 1;
            plants[child] = plants[i];
        }
        let mut pending = attachments[i].iter().peekable();
        let mut first_index = start_index;
        for (segment, w) in b.samples.windows(2).enumerate() {
            let mut last_t = 0.0;
            let mut last_index = first_index;
            while let Some(a) = pending.next_if(|a| a.segment == segment) {
                if (a.t - last_t) * length(sub(xyz(w[1]), xyz(w[0]))) > EPS {
                    last_index = push_point(&mut samples, line, lerp(w[0], w[1], a.t));
                    last_t = a.t;
                }
                junctions[a.child] = Some(last_index);
            }
            first_index = if last_t == 1.0 {
                last_index
            } else {
                push_point(&mut samples, line, w[1])
            };
        }
    }

    let count = samples.len();
    let mut directions = vec![Vec::new(); count];
    let mut distances = vec![0.0; count];
    let mut development = vec![[0; 6]; count];
    let mut status = vec![[0, 0, 0, 0, 0, 1, 1, 1, 0, 0]; count];
    for &i in &order {
        let line = &lines[i];
        for (k, &p) in line.iter().enumerate() {
            if k == 0 && parent_indices[i].is_some() {
                continue;
            }
            let tangent = if let Some(&next) = line.get(k + 1) {
                sub(xyz(samples[next]), xyz(samples[p]))
            } else {
                sub(xyz(samples[p]), xyz(samples[line[k - 1]]))
            };
            if length(tangent) <= EPS {
                return Err(format!(
                    "branch {}: coincident samples after joining",
                    branches[i].id
                ));
            }
            directions[p] = direction_row(unit(tangent));
            development[p][0] = generations[i];
            if k > 0 {
                let prev = line[k - 1];
                distances[p] = distances[prev] + length(sub(xyz(samples[p]), xyz(samples[prev])));
            }
            if k == 0 {
                status[p] = [0, 0, 1, 1, 1, 0, 0, 1, 0, 0];
            } else if k + 1 == line.len() {
                status[p] = [1, 0, 0, 0, 1, 0, 0, 0, 0, 0];
            }
        }
        let mut junction_counts = HashMap::new();
        for &child in &children[i] {
            if let Some(p) = junctions[child] {
                *junction_counts.entry(p).or_insert(0) += 1;
            }
        }
        for (p, count) in junction_counts {
            status[p][2] = 1;
            status[p][6] = count;
        }
    }
    let meristems: Vec<_> = samples
        .iter()
        .zip(&distances)
        .map(|(s, d)| [s[3], 1., 0., 0., 0., *d, 0.])
        .collect();
    let json = json!({
        "points": {
            "positions": samples.iter().copied().map(xyz).collect::<Vec<_>>(),
            "attributes": {
                "budDirection": attr("float", 3, true, json!(directions)),
                "budLateralMeristem": attr("float", 1, true, json!(meristems)),
                "budHormoneLevels": attr("float", 1, true, json!(vec![[0., 0., 0., 0., 1., 0.]; count])),
                "budLightDetected": attr("float", 1, true, json!(vec![[0.; 4]; count])),
                "budDevelopment": attr("int", 1, true, json!(development)),
                "budStatus": attr("int", 1, true, json!(status)),
                "budNumber": attr("int", 1, false, json!((1..=count).collect::<Vec<_>>())),
                "lengthFromRoot": attr("float", 1, false, json!(distances)),
                "lengthFromSeed": attr("float", 1, false, json!(distances)),
            },
        },
        "primitives": {
            "points": lines,
            "attributes": {
                "parents": attr("int", 1, true, json!(parents)),
                "children": attr("int", 1, true, json!(children.iter().map(|row| row.iter().map(|i| i + 1).collect::<Vec<_>>()).collect::<Vec<_>>())),
                "branchNumber": attr("int", 1, false, json!((1..=n).collect::<Vec<_>>())),
                "branchParentNumber": attr("int", 1, false, json!(parents.iter().map(|p| p.last().copied().unwrap_or(0)).collect::<Vec<_>>())),
                "branchSourceBudNumber": attr("int", 1, false, json!(lines.iter().map(|p| p[0] + 1).collect::<Vec<_>>())),
                "branchHierarchyNumber": attr("int", 1, false, json!(generations.iter().map(|g| g - 1).collect::<Vec<_>>())),
                "plantNumber": attr("int", 1, false, json!(plants)),
            },
        },
    });
    Ok((json.to_string(), n, count))
}

fn attr(kind: &str, size: usize, array: bool, values: Value) -> Value {
    json!({ "type": kind, "size": size, "isArray": array, "values": values })
}

#[pyfunction]
fn from_spines(py: Python<'_>, spines: Vec<Spine>) -> PyResult<Export> {
    py.allow_threads(|| {
        encode(
            spines
                .into_iter()
                .map(|(id, parent, samples)| Branch {
                    id,
                    parent,
                    samples,
                    parent_segment: None,
                })
                .collect(),
        )
    })
    .map_err(PyValueError::new_err)
}

#[pyfunction]
fn from_bones(py: Python<'_>, bones: Vec<Bone>) -> PyResult<Export> {
    py.allow_threads(|| bone_branches(bones).and_then(encode))
        .map_err(PyValueError::new_err)
}

#[pymodule]
fn _pve_growth(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(from_spines, module)?)?;
    module.add_function(wrap_pyfunction!(from_bones, module)?)?;
    Ok(())
}
