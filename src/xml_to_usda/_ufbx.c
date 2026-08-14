#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "vendor/ufbx/ufbx.h"

typedef struct { float *data; size_t count, capacity; } FloatBuffer;
typedef struct { int32_t *data; size_t count, capacity; } IntBuffer;

typedef struct {
    char *name;
    IntBuffer face_indices;
} MaterialSlot;

typedef struct {
    MaterialSlot *data;
    size_t count, capacity;
} MaterialSlots;

static int reserve_bytes(void **data, size_t *capacity, size_t required, size_t item_size)
{
    if (required <= *capacity) return 1;
    size_t next = *capacity ? *capacity : 256;
    while (next < required) {
        if (next > SIZE_MAX / 2) { PyErr_NoMemory(); return 0; }
        next *= 2;
    }
    if (next > SIZE_MAX / item_size) { PyErr_NoMemory(); return 0; }
    void *resized = PyMem_Realloc(*data, next * item_size);
    if (!resized) { PyErr_NoMemory(); return 0; }
    *data = resized;
    *capacity = next;
    return 1;
}

static int float_push(FloatBuffer *buffer, float value)
{
    if (!reserve_bytes((void**)&buffer->data, &buffer->capacity, buffer->count + 1, sizeof(float))) return 0;
    buffer->data[buffer->count++] = value;
    return 1;
}

static int int_push(IntBuffer *buffer, int32_t value)
{
    if (!reserve_bytes((void**)&buffer->data, &buffer->capacity, buffer->count + 1, sizeof(int32_t))) return 0;
    buffer->data[buffer->count++] = value;
    return 1;
}

static int float_push_vec2(FloatBuffer *buffer, ufbx_vec2 value)
{
    return float_push(buffer, (float)value.x) && float_push(buffer, (float)value.y);
}

static int float_push_vec3(FloatBuffer *buffer, ufbx_vec3 value)
{
    return float_push(buffer, (float)value.x) && float_push(buffer, (float)value.y) && float_push(buffer, (float)value.z);
}

static int float_push_vec4(FloatBuffer *buffer, ufbx_vec4 value)
{
    return float_push(buffer, (float)value.x) && float_push(buffer, (float)value.y) && float_push(buffer, (float)value.z) && float_push(buffer, (float)value.w);
}

static void free_slots(MaterialSlots *slots)
{
    for (size_t i = 0; i < slots->count; i++) {
        PyMem_Free(slots->data[i].name);
        PyMem_Free(slots->data[i].face_indices.data);
    }
    PyMem_Free(slots->data);
}

static MaterialSlot *get_slot(MaterialSlots *slots, const char *name, size_t length)
{
    for (size_t i = 0; i < slots->count; i++) {
        if (strlen(slots->data[i].name) == length && memcmp(slots->data[i].name, name, length) == 0) return &slots->data[i];
    }
    if (!reserve_bytes((void**)&slots->data, &slots->capacity, slots->count + 1, sizeof(MaterialSlot))) return NULL;
    MaterialSlot *slot = &slots->data[slots->count++];
    memset(slot, 0, sizeof(*slot));
    slot->name = PyMem_Malloc(length + 1);
    if (!slot->name) { PyErr_NoMemory(); return NULL; }
    memcpy(slot->name, name, length);
    slot->name[length] = '\0';
    return slot;
}

static void set_ufbx_error(const char *operation, const ufbx_error *error)
{
    const char *description = error->description.data ? error->description.data : "unknown ufbx error";
    const char *info = error->info_length ? error->info : "";
    PyErr_Format(PyExc_ValueError, "ufbx %s failed: %.*s%.*s%.*s", operation,
        (int)error->description.length, description,
        error->info_length ? 2 : 0, error->info_length ? ": " : "",
        (int)error->info_length, info);
}

static ufbx_scene *load_scene(const char *path, ufbx_load_opts *opts)
{
    ufbx_error error;
    ufbx_scene *scene = ufbx_load_file(path, opts, &error);
    if (!scene) set_ufbx_error("load", &error);
    return scene;
}

static int append_mesh_points(FloatBuffer *points, const ufbx_node *node, const ufbx_mesh *mesh)
{
    for (size_t i = 0; i < mesh->vertices.count; i++) {
        if (!float_push_vec3(points, ufbx_transform_position(&node->node_to_world, mesh->vertices.data[i]))) return 0;
    }
    return 1;
}

static int append_triangles(
    IntBuffer *counts, IntBuffer *indices, FloatBuffer *uvs, FloatBuffer *colors,
    MaterialSlots *slots, const ufbx_node *node, const ufbx_mesh *mesh,
    size_t point_offset, int read_vertex_colors, int read_material_slots,
    int *colors_usable)
{
    uint32_t *tri_indices = PyMem_Malloc(mesh->max_face_triangles * 3 * sizeof(uint32_t));
    if (!tri_indices) { PyErr_NoMemory(); return 0; }
    float *mesh_colors = NULL;
    uint8_t *color_assigned = NULL;
    uint8_t *point_referenced = NULL;
    int mesh_has_colors = 0;
    int color_enabled = read_vertex_colors && *colors_usable;
    if (color_enabled) {
        mesh_colors = PyMem_Calloc(mesh->num_vertices * 4, sizeof(float));
        color_assigned = PyMem_Calloc(mesh->num_vertices, sizeof(uint8_t));
        point_referenced = PyMem_Calloc(mesh->num_vertices, sizeof(uint8_t));
        if (!mesh_colors || !color_assigned || !point_referenced) { PyErr_NoMemory(); goto fail; }
        if (!mesh->vertex_color.exists) {
            *colors_usable = 0;
            color_enabled = 0;
        }
    }

    for (size_t face_index = 0; face_index < mesh->faces.count; face_index++) {
        ufbx_face face = mesh->faces.data[face_index];
        uint32_t triangle_count = ufbx_triangulate_face(
            tri_indices, mesh->max_face_triangles * 3, mesh, face
        );
        if (triangle_count == 0 && face.num_indices >= 3) {
            PyErr_SetString(PyExc_ValueError, "ufbx failed to triangulate an FBX polygon.");
            goto fail;
        }
        MaterialSlot *slot = NULL;
        if (read_material_slots) {
            const char *slot_name = "Unassigned";
            size_t slot_length = strlen(slot_name);
            uint32_t material_index = UFBX_NO_INDEX;
            if (face_index < mesh->face_material.count) material_index = mesh->face_material.data[face_index];
            else if (node->materials.count == 1) material_index = 0;
            if (material_index < node->materials.count && node->materials.data[material_index]) {
                ufbx_string name = node->materials.data[material_index]->name;
                if (name.length) { slot_name = name.data; slot_length = name.length; }
            } else if (material_index != UFBX_NO_INDEX) {
                char generated[48];
                int length = snprintf(generated, sizeof(generated), "MaterialSlot_%u", material_index);
                if (length < 0 || (size_t)length >= sizeof(generated)) { PyErr_SetString(PyExc_ValueError, "ufbx material slot name is invalid."); goto fail; }
                slot_name = generated;
                slot_length = (size_t)length;
            }
            slot = get_slot(slots, slot_name, slot_length);
            if (!slot) goto fail;
        }
        for (uint32_t tri = 0; tri < triangle_count; tri++) {
            if (!int_push(counts, 3) || (slot && !int_push(&slot->face_indices, (int32_t)(counts->count - 1)))) goto fail;
            for (size_t corner = 0; corner < 3; corner++) {
                uint32_t index = tri_indices[tri * 3 + corner];
                if (index >= mesh->vertex_indices.count) { PyErr_SetString(PyExc_ValueError, "ufbx produced an invalid FBX polygon index."); goto fail; }
                uint32_t vertex = mesh->vertex_indices.data[index];
                if (vertex >= mesh->num_vertices) { PyErr_SetString(PyExc_ValueError, "ufbx produced an invalid FBX control-point index."); goto fail; }
                if (!int_push(indices, (int32_t)(point_offset + vertex))) goto fail;
                if (mesh->vertex_uv.exists && !float_push_vec2(uvs, ufbx_get_vertex_vec2(&mesh->vertex_uv, index))) goto fail;
                if (color_enabled) {
                    ufbx_vec4 color = ufbx_get_vertex_vec4(&mesh->vertex_color, index);
                    float values[4] = { (float)color.x, (float)color.y, (float)color.z, (float)color.w };
                    size_t offset = vertex * 4;
                    point_referenced[vertex] = 1;
                    if (color_assigned[vertex] && memcmp(mesh_colors + offset, values, sizeof(values)) != 0) {
                        PyErr_SetString(PyExc_ValueError, "Per-polygon-vertex color splits on shared control points are not supported. Re-export the FBX with non-conflicting vertex colors.");
                        goto fail;
                    }
                    memcpy(mesh_colors + offset, values, sizeof(values));
                    color_assigned[vertex] = 1;
                    mesh_has_colors = 1;
                }
            }
        }
    }
    if (color_enabled) {
        for (size_t vertex = 0; vertex < mesh->num_vertices; vertex++) {
            if (point_referenced[vertex] && !color_assigned[vertex]) { *colors_usable = 0; break; }
        }
        if (mesh_has_colors && *colors_usable) {
            for (size_t i = 0; i < mesh->num_vertices * 4; i++) if (!float_push(colors, mesh_colors[i])) goto fail;
        } else if (!mesh_has_colors) {
            *colors_usable = 0;
        }
    }
    PyMem_Free(tri_indices); PyMem_Free(mesh_colors); PyMem_Free(color_assigned); PyMem_Free(point_referenced);
    return 1;
fail:
    PyMem_Free(tri_indices); PyMem_Free(mesh_colors); PyMem_Free(color_assigned); PyMem_Free(point_referenced);
    return 0;
}

static PyObject *bytes_from_buffer(const void *data, size_t count, size_t size)
{
    if (count > PY_SSIZE_T_MAX / size) { PyErr_NoMemory(); return NULL; }
    return PyBytes_FromStringAndSize((const char*)data, (Py_ssize_t)(count * size));
}

static PyObject *build_slots(const MaterialSlots *slots)
{
    PyObject *result = PyTuple_New((Py_ssize_t)slots->count);
    if (!result) return NULL;
    for (size_t i = 0; i < slots->count; i++) {
        PyObject *name = PyUnicode_FromString(slots->data[i].name);
        PyObject *indices = bytes_from_buffer(slots->data[i].face_indices.data, slots->data[i].face_indices.count, sizeof(int32_t));
        PyObject *entry = name && indices ? PyTuple_Pack(2, name, indices) : NULL;
        Py_XDECREF(name); Py_XDECREF(indices);
        if (!entry) { Py_DECREF(result); return NULL; }
        PyTuple_SET_ITEM(result, (Py_ssize_t)i, entry);
    }
    return result;
}

static PyObject *py_load_geometry(PyObject *self, PyObject *args, PyObject *kwargs)
{
    const char *path;
    int read_colors = 1, read_materials = 1;
    static char *keywords[] = { "path", "read_vertex_colors", "read_material_slots", NULL };
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|pp", keywords, &path, &read_colors, &read_materials)) return NULL;
    ufbx_load_opts opts = { 0 };
    opts.ignore_embedded = true;
    opts.ignore_missing_external_files = true;
    opts.skip_mesh_parts = true;
    ufbx_scene *scene = load_scene(path, &opts);
    if (!scene) return NULL;
    FloatBuffer points = {0}, uvs = {0}, colors = {0};
    IntBuffer counts = {0}, indices = {0};
    MaterialSlots slots = {0};
    PyObject *result = NULL;
    int colors_usable = read_colors;
    size_t point_offset = 0;
    if (scene->anim_stacks.count) { PyErr_SetString(PyExc_ValueError, "Animated FBX files are not supported for Assembly Part import."); goto done; }
    for (size_t node_index = 0; node_index < scene->nodes.count; node_index++) {
        const ufbx_node *node = scene->nodes.data[node_index];
        const ufbx_mesh *mesh = node->mesh;
        if (!mesh) continue;
        if (mesh->all_deformers.count) { PyErr_SetString(PyExc_ValueError, "Deformed FBX meshes are not supported for Assembly Part import."); goto done; }
        if (!append_mesh_points(&points, node, mesh)) goto done;
        if (!append_triangles(&counts, &indices, &uvs, &colors, &slots, node, mesh, point_offset, read_colors, read_materials, &colors_usable)) goto done;
        point_offset += mesh->num_vertices;
    }
    if (!points.count || !counts.count || !indices.count) { PyErr_SetString(PyExc_ValueError, "FBX file does not contain readable mesh topology."); goto done; }
    if (!colors_usable) colors.count = 0;
    result = PyDict_New();
    PyObject *raw_points = bytes_from_buffer(points.data, points.count, sizeof(float));
    PyObject *raw_counts = bytes_from_buffer(counts.data, counts.count, sizeof(int32_t));
    PyObject *raw_indices = bytes_from_buffer(indices.data, indices.count, sizeof(int32_t));
    PyObject *raw_uvs = bytes_from_buffer(uvs.data, uvs.count, sizeof(float));
    PyObject *raw_colors = bytes_from_buffer(colors.data, colors.count, sizeof(float));
    PyObject *raw_slots = read_materials ? build_slots(&slots) : PyTuple_New(0);
    if (!result || !raw_points || !raw_counts || !raw_indices || !raw_uvs || !raw_colors || !raw_slots ||
        PyDict_SetItemString(result, "point_components", raw_points) < 0 ||
        PyDict_SetItemString(result, "face_vertex_counts", raw_counts) < 0 ||
        PyDict_SetItemString(result, "face_vertex_indices", raw_indices) < 0 ||
        PyDict_SetItemString(result, "uv_components", raw_uvs) < 0 ||
        PyDict_SetItemString(result, "vertex_color_components", raw_colors) < 0 ||
        PyDict_SetItemString(result, "material_slots", raw_slots) < 0) {
        Py_XDECREF(result); result = NULL;
    }
    Py_XDECREF(raw_points); Py_XDECREF(raw_counts); Py_XDECREF(raw_indices); Py_XDECREF(raw_uvs); Py_XDECREF(raw_colors); Py_XDECREF(raw_slots);
done:
    PyMem_Free(points.data); PyMem_Free(uvs.data); PyMem_Free(colors.data); PyMem_Free(counts.data); PyMem_Free(indices.data); free_slots(&slots); ufbx_free_scene(scene);
    return result;
}

static PyObject *py_inspect_material_slots(PyObject *self, PyObject *args)
{
    const char *path;
    if (!PyArg_ParseTuple(args, "s", &path)) return NULL;
    ufbx_load_opts opts = { 0 };
    opts.ignore_embedded = true;
    opts.ignore_missing_external_files = true;
    opts.ignore_animation = true;
    opts.skip_mesh_parts = true;
    ufbx_scene *scene = load_scene(path, &opts);
    if (!scene) return NULL;
    MaterialSlots slots = {0};
    size_t face_index = 0;
    PyObject *result = NULL;
    for (size_t node_index = 0; node_index < scene->nodes.count; node_index++) {
        const ufbx_node *node = scene->nodes.data[node_index];
        const ufbx_mesh *mesh = node->mesh;
        if (!mesh) continue;
        uint32_t *tri_indices = PyMem_Malloc(mesh->max_face_triangles * 3 * sizeof(uint32_t));
        if (!tri_indices) { PyErr_NoMemory(); goto done; }
        for (size_t local_face = 0; local_face < mesh->faces.count; local_face++) {
            ufbx_face face = mesh->faces.data[local_face];
            uint32_t triangle_count = ufbx_triangulate_face(
                tri_indices, mesh->max_face_triangles * 3, mesh, face
            );
            if (triangle_count == 0 && face.num_indices >= 3) {
                PyMem_Free(tri_indices);
                PyErr_SetString(PyExc_ValueError, "ufbx failed to triangulate an FBX polygon.");
                goto done;
            }
            uint32_t material_index = local_face < mesh->face_material.count ? mesh->face_material.data[local_face] : (node->materials.count == 1 ? 0 : UFBX_NO_INDEX);
            const char *name = "Unassigned"; size_t length = 10;
            if (material_index < node->materials.count && node->materials.data[material_index] && node->materials.data[material_index]->name.length) {
                name = node->materials.data[material_index]->name.data; length = node->materials.data[material_index]->name.length;
            } else if (material_index != UFBX_NO_INDEX) {
                char generated[48];
                int generated_length = snprintf(generated, sizeof(generated), "MaterialSlot_%u", material_index);
                if (generated_length < 0 || (size_t)generated_length >= sizeof(generated)) {
                    PyMem_Free(tri_indices);
                    PyErr_SetString(PyExc_ValueError, "ufbx material slot name is invalid.");
                    goto done;
                }
                name = generated;
                length = (size_t)generated_length;
            }
            MaterialSlot *slot = get_slot(&slots, name, length);
            if (!slot) { PyMem_Free(tri_indices); goto done; }
            for (uint32_t triangle = 0; triangle < triangle_count; triangle++, face_index++) {
                if (!int_push(&slot->face_indices, (int32_t)face_index)) { PyMem_Free(tri_indices); goto done; }
            }
        }
        PyMem_Free(tri_indices);
    }
    result = PyTuple_New((Py_ssize_t)slots.count);
    if (!result) goto done;
    for (size_t i = 0; i < slots.count; i++) {
        PyObject *entry = Py_BuildValue("(sn)", slots.data[i].name, (Py_ssize_t)slots.data[i].face_indices.count);
        if (!entry) { Py_CLEAR(result); goto done; }
        PyTuple_SET_ITEM(result, (Py_ssize_t)i, entry);
    }
done:
    free_slots(&slots); ufbx_free_scene(scene); return result;
}

static const ufbx_node *bone_parent(const ufbx_node *node)
{
    for (const ufbx_node *parent = node->parent; parent; parent = parent->parent) if (parent->bone) return parent;
    return NULL;
}

static PyObject *py_load_skeleton(PyObject *self, PyObject *args)
{
    const char *path;
    if (!PyArg_ParseTuple(args, "s", &path)) return NULL;
    ufbx_load_opts opts = { 0 };
    opts.ignore_geometry = true;
    opts.ignore_animation = true;
    opts.ignore_embedded = true;
    opts.ignore_missing_external_files = true;
    ufbx_scene *scene = load_scene(path, &opts);
    if (!scene) return NULL;
    PyObject *result = PyList_New(0);
    if (!result) { ufbx_free_scene(scene); return NULL; }
    for (size_t i = 0; i < scene->nodes.count; i++) {
        const ufbx_node *node = scene->nodes.data[i];
        if (!node->bone) continue;
        const char *name = node->name.length ? node->name.data : NULL;
        char generated[32];
        if (!name) { snprintf(generated, sizeof(generated), "joint_%03zu", PyList_GET_SIZE(result)); name = generated; }
        const ufbx_node *parent = bone_parent(node);
        PyObject *entry = Py_BuildValue("(ssddd)", name, parent && parent->name.length ? parent->name.data : "", node->node_to_world.m03, node->node_to_world.m13, node->node_to_world.m23);
        if (!entry || PyList_Append(result, entry) < 0) { Py_XDECREF(entry); Py_CLEAR(result); break; }
        Py_DECREF(entry);
    }
    if (result && PyList_GET_SIZE(result) == 0) { Py_CLEAR(result); PyErr_SetString(PyExc_ValueError, "FBX file does not contain a skeleton."); }
    if (result) {
        PyObject *names = PySet_New(NULL);
        if (!names) { Py_CLEAR(result); }
        for (Py_ssize_t i = 0; result && i < PyList_GET_SIZE(result); i++) {
            PyObject *name = PyTuple_GET_ITEM(PyList_GET_ITEM(result, i), 0);
            int contains = PySet_Contains(names, name);
            if (contains < 0) { Py_CLEAR(result); break; }
            if (contains == 1) { PyErr_Format(PyExc_ValueError, "fbx_skeleton_duplicate_joint_name: %U", name); Py_CLEAR(result); break; }
            if (PySet_Add(names, name) < 0) { Py_CLEAR(result); break; }
        }
        Py_XDECREF(names);
    }
    ufbx_free_scene(scene);
    return result;
}

static PyMethodDef methods[] = {
    { "load_geometry", (PyCFunction)py_load_geometry, METH_VARARGS | METH_KEYWORDS, "Load rigid FBX geometry through ufbx." },
    { "inspect_material_slots", py_inspect_material_slots, METH_VARARGS, "Inspect FBX material slots through ufbx." },
    { "load_skeleton", py_load_skeleton, METH_VARARGS, "Load an FBX bone hierarchy through ufbx." },
    { NULL, NULL, 0, NULL },
};

static struct PyModuleDef module = { PyModuleDef_HEAD_INIT, "_ufbx", NULL, -1, methods };

PyMODINIT_FUNC PyInit__ufbx(void) { return PyModule_Create(&module); }
