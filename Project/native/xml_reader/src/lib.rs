//! Bounded XML opening reader. Geometry interpretation remains in the canonical normalizer.
use pyo3::exceptions::{PyOSError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use roxmltree::{Document, Node, NodeId};
use std::borrow::Cow;
use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::Read;

enum NodeEdge<'a, 'input> {
    Start(Node<'a, 'input>),
    End(Node<'a, 'input>),
}

fn traverse<'a, 'input>(root: Node<'a, 'input>) -> impl Iterator<Item = NodeEdge<'a, 'input>> {
    let mut stack = vec![NodeEdge::Start(root)];
    std::iter::from_fn(move || {
        let edge = stack.pop()?;
        if let NodeEdge::Start(node) = edge {
            stack.push(NodeEdge::End(node));
            stack.extend(node.children().rev().map(NodeEdge::Start));
        }
        Some(edge)
    })
}

fn packed_tag(tag: &str) -> bool {
    matches!(
        tag,
        "X" | "Y"
            | "Z"
            | "Radius"
            | "Scale"
            | "RotAxisX"
            | "RotAxisY"
            | "RotAxisZ"
            | "RotAngle"
            | "MeshID"
            | "MeshLOD"
            | "BoneID"
            | "PointIndices"
            | "TriangleIndices"
            | "QuadIndices"
            | "VertexIndices"
            | "TexcoordU"
            | "TexcoordV"
            | "VertexColorR"
            | "VertexColorG"
            | "VertexColorB"
            | "VertexColorA"
            | "NormalX"
            | "NormalY"
            | "NormalZ"
            | "TangentX"
            | "TangentY"
            | "TangentZ"
            | "BinormalX"
            | "BinormalY"
            | "BinormalZ"
    )
}

// ElementTree concatenates text around comments/PI/CDATA, stopping at the first child element.
fn leading_text<'a>(node: Node<'a, '_>) -> Cow<'a, str> {
    let mut texts = node
        .children()
        .take_while(|child| !child.is_element())
        .filter_map(|child| child.text().filter(|_| child.is_text()));
    let first = texts.next().unwrap_or("");
    let Some(second) = texts.next() else {
        return Cow::Borrowed(first);
    };
    let mut joined = String::with_capacity(first.len() + second.len());
    joined.push_str(first);
    joined.push_str(second);
    for text in texts {
        joined.push_str(text);
    }
    Cow::Owned(joined)
}

fn count_values(text: &str) -> usize {
    if text.is_ascii() {
        let mut count = 0;
        let mut token = false;
        for b in text.bytes() {
            let next = b != b',' && !b.is_ascii_whitespace();
            count += usize::from(next && !token);
            token = next;
        }
        count
    } else {
        text.split(|c: char| c == ',' || c.is_whitespace())
            .filter(|v| !v.is_empty())
            .count()
    }
}

fn escaped(out: &mut String, text: &str, attribute: bool) {
    for c in text.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' if attribute => out.push_str("&quot;"),
            '\n' if attribute => out.push_str("&#10;"),
            '\r' if attribute => out.push_str("&#13;"),
            '\t' if attribute => out.push_str("&#9;"),
            '\r' => out.push_str("&#13;"),
            _ => out.push(c),
        }
    }
}

fn check(actual: usize, limit: usize, label: &str) -> Result<(), String> {
    if actual > limit {
        Err(format!(
            "{label} exceeds source budget: {actual} > {limit}."
        ))
    } else {
        Ok(())
    }
}

type OpeningFacts = (Vec<(i64, String)>, Vec<(Option<i64>, String, usize)>, usize);
type OpeningPayload = (Vec<u8>, bool, Option<OpeningFacts>);
type PythonOpening<'py> = (Bound<'py, PyBytes>, bool, Option<OpeningFacts>);

fn first_field<'a>(node: Node<'a, '_>, tag: &str) -> Cow<'a, str> {
    node.children()
        .find(|c| c.has_tag_name(tag))
        .map(leading_text)
        .unwrap_or_default()
}

fn integer(text: &str) -> Option<i64> {
    if !text.is_ascii() {
        return None;
    }
    text.parse().ok()
}

fn required_count(text: &str) -> Option<usize> {
    // Unusual numeric spellings retain the authoritative Python payload reader.
    if !text.is_ascii() || text.contains(',') {
        return None;
    }
    text.split_ascii_whitespace()
        .try_fold(0usize, |count, value| {
            value.parse::<f64>().ok().map(|_| count + 1)
        })
}

fn opening_facts(root: Node<'_, '_>) -> Option<OpeningFacts> {
    let mut names = HashMap::<i64, String>::new();
    let mut material_order = Vec::new();
    let mut used_materials = HashSet::new();
    let mut mesh_names = HashMap::<i64, String>::new();
    let mut mesh_order = Vec::new();
    let mut counts = HashMap::<i64, usize>::new();
    let mut fallback_count = 0usize;
    let mut canonical_count = 0usize;
    let mut object_depth = 0;
    let mut mesh_depth = 0;
    for edge in traverse(root) {
        match edge {
            NodeEdge::Start(node) if node.is_element() => match node.tag_name().name() {
                "Object" => object_depth += 1,
                "Mesh" => mesh_depth += 1,
                "Bone" | "LeafReferences"
                    if node
                        .ancestors()
                        .skip(1)
                        .any(|a| a.tag_name() == node.tag_name()) =>
                {
                    return None
                }
                _ => (),
            },
            NodeEdge::End(node) if node.is_element() => match node.tag_name().name() {
                "Material" => {
                    if let Some(raw) = node.attribute("ID") {
                        if !raw.trim_start_matches('-').is_empty()
                            && raw.trim_start_matches('-').chars().all(|c| c.is_numeric())
                        {
                            let id = integer(raw)?;
                            if !names.contains_key(&id) {
                                material_order.push(id);
                            }
                            names.insert(
                                id,
                                node.attribute("Name")
                                    .map(str::to_owned)
                                    .unwrap_or_else(|| format!("Material_{id}")),
                            );
                        }
                    }
                }
                "Triangles" if object_depth > 0 && mesh_depth == 0 => {
                    if let Some(raw) = node.attribute("Material") {
                        if !raw.trim_start_matches('-').is_empty()
                            && raw.trim_start_matches('-').chars().all(|c| c.is_numeric())
                        {
                            used_materials.insert(integer(raw)?);
                        }
                    }
                }
                "Mesh" => {
                    if let Some(raw) = node.attribute("ID") {
                        if !raw.is_empty() && raw.chars().all(|c| c.is_numeric()) {
                            let id = integer(raw)?;
                            mesh_names.insert(
                                id,
                                node.attribute("Name")
                                    .map(str::to_owned)
                                    .unwrap_or_else(|| format!("Mesh_{id}")),
                            );
                        }
                    }
                    mesh_depth -= 1;
                }
                "Object" => object_depth -= 1,
                "LeafReferences" => {
                    let raw = first_field(node, "MeshID");
                    let mut ids = Vec::new();
                    for token in raw
                        .split(|c: char| c == ',' || c.is_whitespace())
                        .filter(|v| !v.is_empty())
                    {
                        if !token.trim_start_matches('-').is_empty()
                            && token
                                .trim_start_matches('-')
                                .chars()
                                .all(|c| c.is_numeric())
                        {
                            ids.push(integer(token)?);
                        }
                    }
                    let count = match node.attribute("Count").map(str::trim) {
                        Some(raw)
                            if !raw.is_empty()
                                && raw.bytes().all(|b| b.is_ascii_digit())
                                && integer(raw)? > 0 =>
                        {
                            usize::try_from(integer(raw)?).ok()?
                        }
                        _ => ["MeshID", "X", "Y", "Z", "Scale", "BoneID"]
                            .iter()
                            .map(|tag| first_field(node, tag).split_whitespace().count())
                            .max()
                            .unwrap_or(0),
                    };
                    if node
                        .attribute("Count")
                        .is_some_and(|v| !v.is_ascii() && v.trim().chars().all(char::is_numeric))
                    {
                        return None;
                    }
                    if ids.is_empty() {
                        if ["MeshID", "X", "Y", "Z"]
                            .iter()
                            .any(|tag| !first_field(node, tag).trim().is_empty())
                        {
                            fallback_count = fallback_count.checked_add(count.max(1))?;
                        }
                    } else {
                        for id in &ids {
                            if !counts.contains_key(id) {
                                mesh_order.push(*id);
                                counts.insert(*id, 0);
                            }
                        }
                        if ids.len() == 1 && count > 1 {
                            let current = counts.get_mut(&ids[0])?;
                            *current = current.checked_add(count)?;
                        } else {
                            for id in ids {
                                let current = counts.get_mut(&id)?;
                                *current = current.checked_add(1)?;
                            }
                        }
                    }
                    if node.parent().is_some_and(|p| p.has_tag_name("Object")) {
                        let mut lengths = [0; 3];
                        for (index, tag) in ["X", "Y", "Z"].iter().enumerate() {
                            let field = node.children().filter(|c| c.has_tag_name(*tag)).last();
                            lengths[index] =
                                required_count(&field.map(leading_text).unwrap_or_default())?;
                        }
                        canonical_count = canonical_count.checked_add(*lengths.iter().min()?)?;
                    }
                }
                _ => (),
            },
            _ => (),
        }
    }
    let materials = material_order
        .into_iter()
        .filter(|id| used_materials.contains(id))
        .map(|id| (id, names.remove(&id).unwrap_or_default()))
        .collect();
    let prototypes = if mesh_order.is_empty() && fallback_count > 0 {
        vec![(None, "LeafPrototype".to_owned(), fallback_count)]
    } else {
        mesh_order
            .into_iter()
            .map(|id| {
                (
                    Some(id),
                    mesh_names
                        .remove(&id)
                        .unwrap_or_else(|| format!("Mesh_{id}")),
                    counts[&id],
                )
            })
            .collect()
    };
    Some((materials, prototypes, canonical_count))
}

fn compatible_encoding(bytes: &[u8]) -> bool {
    let bytes = bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(bytes);
    if !bytes.starts_with(b"<?xml") {
        return true;
    }
    let Some(end) = bytes.windows(2).position(|s| s == b"?>") else {
        return true;
    };
    let declaration = String::from_utf8_lossy(&bytes[..end]);
    let Some(index) = declaration.find("encoding") else {
        return true;
    };
    let value = declaration[index + 8..]
        .trim_start()
        .strip_prefix('=')
        .unwrap_or("")
        .trim_start();
    let Some(quote) = value.chars().next() else {
        return true;
    };
    if quote != '\'' && quote != '"' {
        return true;
    }
    let encoding = value[1..]
        .split(quote)
        .next()
        .unwrap_or("")
        .to_ascii_lowercase();
    encoding == "utf-8" || encoding == "utf8" || (encoding == "us-ascii" && bytes.is_ascii())
}

fn project(
    bytes: Vec<u8>,
    limits: [usize; 6],
    projection: bool,
) -> Result<Option<OpeningPayload>, String> {
    for token in [b"<!doctype".as_slice(), b"<!entity".as_slice()] {
        if bytes
            .windows(token.len())
            .any(|v| v.eq_ignore_ascii_case(token))
        {
            return Err("SpeedTree XML must not contain DTD or entity declarations.".into());
        }
    }
    if !compatible_encoding(&bytes) {
        return Ok(None);
    }
    let Ok(text) = std::str::from_utf8(&bytes) else {
        return Ok(None);
    };
    let doc = Document::parse(text).map_err(|e| format!("Invalid SpeedTree XML: {e}"))?;
    let root = doc.root_element();
    let mut depth = 0;
    let mut total = 0;
    let mut faces = 0;
    let mut instances = 0;
    let mut keep = HashSet::<NodeId>::new();
    let mut all_text_depth = 0;
    let mut bones = 0;
    let mut namespaced = false;
    let mut nested_bones = false;
    let mut nested_structure = false;
    let mut nested_units = None;
    let mut nested_axis = None;
    let mut nested_axis_alt = None;
    for edge in traverse(root) {
        match edge {
            NodeEdge::Start(node) if node.is_element() => {
                depth += 1;
                check(depth, limits[1], "XML depth")?;
                let tag = node.tag_name().name();
                if matches!(tag, "Bone" | "Object" | "Mesh" | "Material") {
                    nested_structure |= node
                        .ancestors()
                        .skip(1)
                        .any(|n| n.has_tag_name("LeafReferences"));
                }
                namespaced |= node.tag_name().namespace().is_some()
                    || node.namespaces().len() > 0
                    || node.attributes().any(|attr| attr.namespace().is_some());
                if namespaced {
                    return Ok(None);
                }
                if nested_units.is_none() {
                    nested_units = node.attribute("units");
                }
                if nested_axis.is_none() {
                    nested_axis = node.attribute("upAxis");
                }
                if nested_axis_alt.is_none() {
                    nested_axis_alt = node.attribute("up_axis");
                }
                if packed_tag(tag) {
                    let count = count_values(&leading_text(node));
                    if count > limits[2] {
                        return Err(format!(
                            "Packed XML field {tag} exceeds source budget: {count} > {}.",
                            limits[2]
                        ));
                    }
                    total += count;
                    check(total, limits[3], "Packed XML values")?;
                    if matches!(
                        tag,
                        "PointIndices" | "TriangleIndices" | "QuadIndices" | "VertexIndices"
                    ) {
                        faces += count;
                        check(faces, limits[5], "Mesh face-vertex entries")?;
                    }
                }
                if tag == "LeafReferences" {
                    instances += ["MeshID", "X", "Y", "Z"]
                        .iter()
                        .map(|tag| {
                            node.children()
                                .find(|c| c.has_tag_name(*tag))
                                .map(|n| count_values(&leading_text(n)))
                                .unwrap_or(0)
                        })
                        .max()
                        .unwrap_or(0);
                    check(instances, limits[4], "Repeated Part Instances")?;
                }
                if tag == "Bone" {
                    bones += 1;
                    nested_bones |= node.ancestors().skip(1).any(|n| n.has_tag_name("Bone"));
                }
                if all_text_depth == 0 && matches!(tag, "Bone" | "LeafReferences") {
                    all_text_depth = depth;
                }
                if all_text_depth > 0
                    || matches!(tag, "Object" | "Mesh" | "Material" | "Points" | "Triangles")
                {
                    let mut ancestor = Some(node);
                    while let Some(n) = ancestor {
                        if !keep.insert(n.id()) {
                            break;
                        }
                        ancestor = n.parent();
                    }
                }
            }
            NodeEdge::End(node) if node.is_element() => {
                if all_text_depth == depth {
                    all_text_depth = 0;
                }
                depth -= 1;
            }
            _ => (),
        }
    }
    // Preserve Python's expanded-name/legacy-encoding behavior rather than partially interpreting it.
    if namespaced || nested_bones || nested_structure {
        return Ok(None);
    }
    if !projection || bones == 0 {
        return Ok(Some((bytes, false, None)));
    }
    let facts = opening_facts(root);
    if facts.is_some() {
        // Keep only structural stubs for LeafReferences. Their scalar UI facts
        // have already been collected; packed arrays never cross the FFI.
        for node in root.descendants().filter(|n| n.is_element()) {
            if node
                .ancestors()
                .skip(1)
                .any(|n| n.has_tag_name("LeafReferences"))
            {
                keep.remove(&node.id());
            }
        }
    }
    keep.insert(root.id());
    let units = root
        .attribute("units")
        .filter(|v| !v.is_empty())
        .or(nested_units);
    let axis = root
        .attribute("upAxis")
        .filter(|v| !v.is_empty())
        .or_else(|| root.attribute("up_axis").filter(|v| !v.is_empty()))
        .or(nested_axis)
        .filter(|v| !v.is_empty())
        .or(nested_axis_alt);
    let mut out = String::with_capacity(bytes.len() / 16);
    let mut text_depth = 0;
    let mut current_depth = 0;
    for edge in traverse(root) {
        match edge {
            NodeEdge::Start(node) if node.is_element() => {
                current_depth += 1;
                if !keep.contains(&node.id()) {
                    continue;
                }
                let tag = node.tag_name().name();
                out.push('<');
                out.push_str(tag);
                for attr in node.attributes() {
                    if node == root && matches!(attr.name(), "units" | "upAxis" | "up_axis") {
                        continue;
                    }
                    out.push(' ');
                    out.push_str(attr.name());
                    out.push_str("=\"");
                    escaped(&mut out, attr.value(), true);
                    out.push('"');
                }
                if node == root {
                    for (key, value) in [("units", units), ("upAxis", axis)] {
                        if let Some(value) = value {
                            out.push(' ');
                            out.push_str(key);
                            out.push_str("=\"");
                            escaped(&mut out, value, true);
                            out.push('"');
                        }
                    }
                }
                out.push('>');
                if text_depth == 0
                    && (tag == "Bone" || (tag == "LeafReferences" && facts.is_none()))
                {
                    text_depth = current_depth;
                }
            }
            NodeEdge::Start(node) if node.is_text() && text_depth > 0 => {
                escaped(&mut out, node.text().unwrap_or(""), false);
            }
            NodeEdge::End(node) if node.is_element() => {
                if keep.contains(&node.id()) {
                    out.push_str("</");
                    out.push_str(node.tag_name().name());
                    out.push('>');
                }
                if current_depth == text_depth {
                    text_depth = 0;
                }
                current_depth -= 1;
            }
            _ => (),
        }
    }
    Ok(Some((out.into_bytes(), true, facts)))
}

#[pyfunction]
#[pyo3(signature = (path, limits, projection=true))]
fn read_opening(
    py: Python<'_>,
    path: String,
    limits: [usize; 6],
    projection: bool,
) -> PyResult<Option<PythonOpening<'_>>> {
    let result = py.allow_threads(move || {
        let file = File::open(path).map_err(|e| PyOSError::new_err(e.to_string()))?;
        let size = file
            .metadata()
            .map_err(|e| PyOSError::new_err(e.to_string()))?
            .len();
        let size = usize::try_from(size)
            .map_err(|_| PyValueError::new_err("XML file size exceeds addressable memory"))?;
        check(size, limits[0], "XML file size").map_err(PyValueError::new_err)?;
        let mut bytes = Vec::with_capacity(size);
        file.take(
            u64::try_from(limits[0])
                .unwrap_or(u64::MAX)
                .saturating_add(1),
        )
        .read_to_end(&mut bytes)
        .map_err(|e| PyOSError::new_err(e.to_string()))?;
        check(bytes.len(), limits[0], "XML file size").map_err(PyValueError::new_err)?;
        project(bytes, limits, projection).map_err(PyValueError::new_err)
    })?;
    Ok(result.map(|(bytes, projected, facts)| (PyBytes::new(py, &bytes), projected, facts)))
}

#[pymodule]
fn _xml_reader(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("API_VERSION", 1)?;
    module.add_function(wrap_pyfunction!(read_opening, module)?)?;
    Ok(())
}
