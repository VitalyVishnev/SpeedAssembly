"""One opaque unlit GPU batch for bones; hardware depth orders the strokes."""

from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject


class OpaqueBoneRenderer:
    def __init__(self, parent):
        self.program = QOpenGLShaderProgram()
        vertex = """
            attribute vec3 position;
            attribute vec3 color;
            attribute vec4 metric;
            attribute vec2 depths;
            attribute vec4 shadows0;
            attribute vec4 shadows1;
            varying vec3 boneColor;
            varying vec4 stroke;
            varying vec2 sourceDepth;
            varying vec4 centers0;
            varying vec4 centers1;
            void main() {
                gl_Position = vec4(position, 1.0);
                boneColor = color;
                stroke = metric;
                sourceDepth = depths;
                centers0 = shadows0;
                centers1 = shadows1;
            }
        """
        fragment = """
            varying vec3 boneColor;
            varying vec4 stroke;
            varying vec2 sourceDepth;
            varying vec4 centers0;
            varying vec4 centers1;
            uniform float shadowStrength;
            uniform float shadowRadius;
            void main() {
                float beyondEnd = max(max(-stroke.x, stroke.x - stroke.z), 0.0);
                if (length(vec2(beyondEnd, stroke.y)) > stroke.w) discard;
                float t = stroke.z > 0.000001 ? clamp(stroke.x / stroke.z, 0.0, 1.0) : 0.0;
                float depth = stroke.z > 0.000001 ? mix(sourceDepth.x, sourceDepth.y, t) : min(sourceDepth.x, sourceDepth.y);
                gl_FragDepth = (depth + 1.0) * 0.5;
                float shadow = 0.0;
                if (shadowStrength > 0.0 && shadowRadius > 0.0) {
                    vec4 d0 = abs(vec4(stroke.x) - centers0);
                    vec4 d1 = abs(vec4(stroke.x) - centers1);
                    float distance = min(min(min(d0.x, d0.y), min(d0.z, d0.w)), min(min(d1.x, d1.y), min(d1.z, d1.w)));
                    shadow = 1.0 - smoothstep(0.0, shadowRadius, distance);
                }
                gl_FragColor = vec4(boneColor * (1.0 - shadowStrength * shadow), 1.0);
            }
        """
        for kind, source in ((QOpenGLShader.ShaderTypeBit.Vertex, vertex), (QOpenGLShader.ShaderTypeBit.Fragment, fragment)):
            if not self.program.addShaderFromSourceCode(kind, source):
                raise RuntimeError(self.program.log())
        if not self.program.link():
            raise RuntimeError(self.program.log())
        self.vao = QOpenGLVertexArrayObject(parent)
        self.vao.create()
        self.buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.buffer.create()
        self.buffer.setUsagePattern(QOpenGLBuffer.UsagePattern.DynamicDraw)
        self.key = None
        self.count = 0

    def draw(self, functions, vertices, key, strength, radius):
        if not len(vertices):
            return
        self.vao.bind()
        self.buffer.bind()
        self.program.bind()
        if key != self.key:
            self.buffer.allocate(vertices.tobytes(), vertices.nbytes)
            self.count = len(vertices)
            for name, offset, size in (("position", 0, 3), ("color", 3, 3), ("metric", 6, 4), ("depths", 10, 2), ("shadows0", 12, 4), ("shadows1", 16, 4)):
                location = self.program.attributeLocation(name)
                self.program.enableAttributeArray(location)
                self.program.setAttributeBuffer(location, 0x1406, offset * 4, size, 20 * 4)
            self.key = key
        # Bones stay above meshes, but order among themselves is real depth.
        functions.glDisable(0x0BE2)  # GL_BLEND: output is opaque, including shadows.
        functions.glDisable(0x0B44)  # GL_CULL_FACE: screen-aligned quads.
        functions.glEnable(0x0B71)   # GL_DEPTH_TEST
        functions.glDepthMask(True)
        functions.glDepthFunc(0x0201)  # GL_LESS
        functions.glClear(0x00000100)  # Clear only mesh depth, retaining mesh color.
        for name, value in (("shadowStrength", strength), ("shadowRadius", radius)):
            functions.glUniform1f(self.program.uniformLocation(name), float(value))
        functions.glDrawArrays(0x0004, 0, self.count)  # GL_TRIANGLES
        self.program.release()
        self.buffer.release()
        self.vao.release()

    def destroy(self):
        self.buffer.destroy()
        self.vao.destroy()
        self.program.release()
        self.program.removeAllShaders()
