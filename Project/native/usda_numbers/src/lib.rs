//! Numerical USDA text only. Scene semantics and atomic publication stay in Python.
use pyo3::buffer::PyBuffer;
use pyo3::exceptions::{PyMemoryError, PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyInt, PyTuple};
use std::collections::HashMap;
use std::ffi::CStr;
use std::fmt::Write;

const MAX_VALUES: usize = 4096;

fn push_float(_py: Python<'_>, out: &mut String, value: f64) -> PyResult<()> {
    // SAFETY: the Python token holds the GIL. CPython returns a NUL-terminated
    // allocation or null; the allocation is read before being freed exactly once.
    unsafe {
        let ptr = pyo3::ffi::PyOS_double_to_string(value, b'g' as _, 6, 0, std::ptr::null_mut());
        if ptr.is_null() {
            return Err(PyMemoryError::new_err(
                "USDA float formatting allocation failed",
            ));
        }
        let result = CStr::from_ptr(ptr)
            .to_str()
            .map(|text| out.push_str(text))
            .map_err(|error| PyRuntimeError::new_err(error.to_string()));
        pyo3::ffi::PyMem_Free(ptr.cast());
        result
    }
}

#[pyfunction]
fn format_vectors(
    coords: &Bound<'_, PyTuple>,
    width: usize,
    cache_identity: bool,
) -> PyResult<String> {
    if !matches!(width, 2 | 3) || coords.len() > MAX_VALUES {
        return Err(PyValueError::new_err(
            "USDA vectors require width 2 or 3 and at most 4096 values",
        ));
    }
    let py = coords.py();
    let mut out = String::with_capacity(coords.len() * width * 10);
    let mut cache = HashMap::<usize, String>::new();
    let x = pyo3::intern!(py, "x");
    let y = pyo3::intern!(py, "y");
    let z = pyo3::intern!(py, "z");
    for (index, coord) in coords.iter().enumerate() {
        if index != 0 {
            out.push_str(", ");
        }
        let key = coord.as_ptr() as usize;
        if cache_identity {
            if let Some(text) = cache.get(&key) {
                out.push_str(text);
                continue;
            }
        }
        let start = out.len();
        out.push('(');
        push_float(py, &mut out, coord.getattr(x)?.extract()?)?;
        out.push_str(", ");
        push_float(py, &mut out, coord.getattr(y)?.extract()?)?;
        if width == 3 {
            out.push_str(", ");
            push_float(py, &mut out, coord.getattr(z)?.extract()?)?;
        }
        out.push(')');
        if cache_identity {
            cache.insert(key, out[start..].to_owned());
        }
    }
    Ok(out)
}

#[pyfunction]
fn format_ints(values: &Bound<'_, PyTuple>) -> PyResult<String> {
    if values.len() > MAX_VALUES {
        return Err(PyValueError::new_err(
            "USDA integer chunks are limited to 4096 values",
        ));
    }
    let mut out = String::with_capacity(values.len() * 5);
    for (index, value) in values.iter().enumerate() {
        if index != 0 {
            out.push_str(", ");
        }
        if value.is_exact_instance_of::<PyInt>() {
            if let Ok(integer) = value.extract::<i64>() {
                write!(out, "{integer}")
                    .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
                continue;
            }
        }
        // Preserve Python's arbitrary-size integers and str() for subclasses.
        out.push_str(value.str()?.to_str()?);
    }
    Ok(out)
}

#[pyclass]
struct FloatBufferFormatter {
    buffer: PyBuffer<f32>,
    width: usize,
    cache_uvs: bool,
    cache: HashMap<(u32, u32), String>,
}

#[pymethods]
impl FloatBufferFormatter {
    fn chunk(&mut self, py: Python<'_>, start: usize, end: usize) -> PyResult<String> {
        let slice = self
            .buffer
            .as_slice(py)
            .ok_or_else(|| PyValueError::new_err("contiguous float32 buffer required"))?;
        let width = self.width;
        if start > end
            || end > slice.len()
            || start % width != 0
            || end % width != 0
            || (end - start) / width > MAX_VALUES
        {
            return Err(PyValueError::new_err("invalid USDA float32 chunk shape"));
        }
        let mut out = String::with_capacity((end - start) * 10);
        for (index, components) in slice[start..end].chunks_exact(width).enumerate() {
            if index != 0 {
                out.push_str(", ");
            }
            let key = if self.cache_uvs {
                let u = components[0].get();
                let v = components[1].get();
                // Python float-pair keys merge signed zeros, but NaNs never match.
                // Keep this cache across chunks to retain the first zero spelling.
                if u.is_nan() || v.is_nan() {
                    None
                } else {
                    let bits = |value: f32| if value == 0.0 { 0 } else { value.to_bits() };
                    Some((bits(u), bits(v)))
                }
            } else {
                None
            };
            if let Some(key) = key {
                if let Some(text) = self.cache.get(&key) {
                    out.push_str(text);
                    continue;
                }
            }
            let begin = out.len();
            if width > 1 {
                out.push('(');
            }
            for (axis, value) in components.iter().enumerate() {
                if axis != 0 {
                    out.push_str(", ");
                }
                push_float(py, &mut out, f64::from(value.get()))?;
            }
            if width > 1 {
                out.push(')');
            }
            if let Some(key) = key {
                self.cache.insert(key, out[begin..].to_owned());
            }
        }
        Ok(out)
    }
}

#[pyfunction]
fn float_buffer_formatter(
    values: &Bound<'_, PyAny>,
    width: usize,
    cache_uvs: bool,
) -> PyResult<FloatBufferFormatter> {
    if !matches!(width, 1..=4) || (cache_uvs && width != 2) {
        return Err(PyValueError::new_err("invalid USDA packed formatter width"));
    }
    let buffer = PyBuffer::<f32>::get(values)?;
    if buffer.dimensions() != 1 || !buffer.is_c_contiguous() || buffer.item_count() % width != 0 {
        return Err(PyValueError::new_err(
            "USDA requires a contiguous one-dimensional float32 buffer aligned to its vector width",
        ));
    }
    Ok(FloatBufferFormatter {
        buffer,
        width,
        cache_uvs,
        cache: HashMap::new(),
    })
}

#[pyfunction]
fn format_int_buffer(values: &Bound<'_, PyAny>, start: usize, end: usize) -> PyResult<String> {
    let buffer = PyBuffer::<i32>::get(values)?;
    if buffer.dimensions() != 1 {
        return Err(PyValueError::new_err(
            "USDA requires a one-dimensional int32 buffer",
        ));
    }
    let slice = buffer
        .as_slice(values.py())
        .ok_or_else(|| PyValueError::new_err("contiguous int32 buffer required"))?;
    if start > end || end > slice.len() || end - start > MAX_VALUES {
        return Err(PyValueError::new_err("invalid USDA int32 chunk shape"));
    }
    let mut out = String::with_capacity((end - start) * 5);
    for (index, value) in slice[start..end].iter().enumerate() {
        if index != 0 {
            out.push_str(", ");
        }
        write!(out, "{}", value.get())
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    }
    Ok(out)
}

#[pymodule]
fn _usda_numbers(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("API_VERSION", 1)?;
    module.add_function(wrap_pyfunction!(format_vectors, module)?)?;
    module.add_function(wrap_pyfunction!(format_ints, module)?)?;
    module.add_function(wrap_pyfunction!(float_buffer_formatter, module)?)?;
    module.add_function(wrap_pyfunction!(format_int_buffer, module)?)?;
    module.add_class::<FloatBufferFormatter>()?;
    Ok(())
}
