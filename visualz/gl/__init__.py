"""ES 2.0 helpers. Create Context on the main thread before GPU resources.

All resources expose close(); callers own their lifetime and the current context.
Positions/UVs use a triangle strip. Texture bytes are top-to-bottom RGBA.
"""

import os

VERTEX = """attribute vec2 position;
attribute vec2 texcoord;
varying vec2 uv;
void main(){uv=texcoord;
gl_Position=vec4(position,0.0,1.0);}"""
TEXTURED = """precision mediump float;
varying vec2 uv; uniform sampler2D image; uniform float opacity;
void main(){gl_FragColor=texture2D(image,uv)*vec4(1.,1.,1.,opacity);}"""


def api():
    from OpenGL import GLES2

    return GLES2


class Context:
    """Context(size=(1280,720), window=False): SDL KMS/DRM or desktop ES 2."""

    def __init__(self, size=(1280, 720), window=False):
        if not window:
            os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
            os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
        import pygame

        self.pygame = pygame
        try:
            pygame.display.init()
            pygame.display.gl_set_attribute(
                pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES
            )
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 2)
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 0)
            pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
            flags = pygame.OPENGL | pygame.DOUBLEBUF
            if not window:
                flags |= pygame.FULLSCREEN
            pygame.display.set_mode(size, flags)
            pygame.mouse.set_visible(window)
            self.size = size
            gl = api()
            gl.glViewport(0, 0, *size)
        except Exception as exc:
            pygame.display.quit()
            raise RuntimeError(f"SDL could not open an ES 2.0 display: {exc}") from exc

    def running(self):
        return not any(
            e.type == self.pygame.QUIT
            or (e.type == self.pygame.KEYDOWN and e.key == self.pygame.K_ESCAPE)
            for e in self.pygame.event.get()
        )

    def swap(self):
        self.pygame.display.flip()

    def close(self):
        self.pygame.display.quit()


class Program:
    """Program(fragment, vertex=VERTEX): compile and link with readable diagnostics."""

    def __init__(self, fragment, vertex=VERTEX):
        gl = api()
        self.id = gl.glCreateProgram()
        shaders = []
        try:
            for kind, source in [(gl.GL_VERTEX_SHADER, vertex), (gl.GL_FRAGMENT_SHADER, fragment)]:
                shader = gl.glCreateShader(kind)
                shaders.append(shader)
                gl.glShaderSource(shader, source)
                gl.glCompileShader(shader)
                if not gl.glGetShaderiv(shader, gl.GL_COMPILE_STATUS):
                    raise ValueError(
                        f"Shader compilation failed:\n{gl.glGetShaderInfoLog(shader)}\n{source}"
                    )
                gl.glAttachShader(self.id, shader)
            gl.glLinkProgram(self.id)
            if not gl.glGetProgramiv(self.id, gl.GL_LINK_STATUS):
                raise ValueError(f"Shader link failed: {gl.glGetProgramInfoLog(self.id)}")
        except Exception:
            gl.glDeleteProgram(self.id)
            raise
        finally:
            for shader in shaders:
                gl.glDeleteShader(shader)

    def use(self, **uniforms):
        """Bind; float scalars/vectors. Set sampler uniforms explicitly with glUniform1i."""
        gl = api()
        gl.glUseProgram(self.id)
        for name, value in uniforms.items():
            location = gl.glGetUniformLocation(self.id, name)
            values = value if isinstance(value, (tuple, list)) else (value,)
            getattr(gl, f"glUniform{len(values)}f")(location, *values)

    def close(self):
        api().glDeleteProgram(self.id)


class Quad:
    """Quad(bounds=(-1,-1,1,1), flip_v=False): clip-space geometry.

    Default UVs suit top-to-bottom Pillow uploads. Use flip_v=True when sampling
    Framebuffer.texture (GL bottom-to-top) for upscale or ping-pong feedback."""

    def __init__(self, bounds=(-1, -1, 1, 1), flip_v=False):
        import numpy as np

        gl = api()
        left, bottom, right, top = bounds
        vertices = np.array(
            [left, bottom, 0, 1, right, bottom, 1, 1, left, top, 0, 0, right, top, 1, 0],
            dtype="float32",
        )
        if flip_v:
            vertices[3::4] = 1 - vertices[3::4]
        self.id = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.id)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)

    def draw(self, program, texture=None, opacity=1):
        from ctypes import c_void_p

        gl = api()
        gl.glUseProgram(program.id)
        if texture:
            texture.bind()
            gl.glUniform1i(gl.glGetUniformLocation(program.id, "image"), 0)
            gl.glUniform1f(gl.glGetUniformLocation(program.id, "opacity"), opacity)
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        location = gl.glGetAttribLocation(program.id, "position")
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.id)
        gl.glEnableVertexAttribArray(location)
        gl.glVertexAttribPointer(location, 2, gl.GL_FLOAT, False, 16, c_void_p(0))
        texcoord = gl.glGetAttribLocation(program.id, "texcoord")
        if texcoord >= 0:
            gl.glEnableVertexAttribArray(texcoord)
            gl.glVertexAttribPointer(texcoord, 2, gl.GL_FLOAT, False, 16, c_void_p(8))
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glDisableVertexAttribArray(location)
        if texcoord >= 0:
            gl.glDisableVertexAttribArray(texcoord)
        if texture:
            gl.glDisable(gl.GL_BLEND)

    def close(self):
        api().glDeleteBuffers(1, [self.id])


class Texture:
    """Texture(size, data=None): RGBA bytes or Pillow image, max hardware texture size."""

    def __init__(self, size, data=None):
        gl = api()
        self.size = tuple(size)
        limit = int(gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE))
        if any(v < 1 or v > limit for v in size):
            raise ValueError(f"Texture dimensions must be 1..{limit}")
        self.id = gl.glGenTextures(1)
        self.bind()
        for parameter in (gl.GL_TEXTURE_MIN_FILTER, gl.GL_TEXTURE_MAG_FILTER):
            gl.glTexParameteri(gl.GL_TEXTURE_2D, parameter, gl.GL_LINEAR)
        for parameter in (gl.GL_TEXTURE_WRAP_S, gl.GL_TEXTURE_WRAP_T):
            gl.glTexParameteri(gl.GL_TEXTURE_2D, parameter, gl.GL_CLAMP_TO_EDGE)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, *self.size, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None
        )
        if data is not None:
            self.update(data)

    def bind(self, unit=0):
        gl = api()
        gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.id)

    def update(self, data):
        if hasattr(data, "convert"):
            if data.size != self.size:
                raise ValueError("Image size does not match texture")
            data = data.convert("RGBA").tobytes()
        if len(data) != self.size[0] * self.size[1] * 4:
            raise ValueError("Expected width*height*4 RGBA bytes")
        gl = api()
        self.bind()
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexSubImage2D(
            gl.GL_TEXTURE_2D, 0, 0, 0, *self.size, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data
        )

    def close(self):
        api().glDeleteTextures(1, [self.id])


class Framebuffer:
    """Framebuffer(size): colour texture target. bind() also sets viewport."""

    def __init__(self, size):
        gl = api()
        self.texture = Texture(size)
        self.id = gl.glGenFramebuffers(1)
        self.bind()
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D, self.texture.id, 0
        )
        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            self.close()
            raise RuntimeError("Incomplete ES 2 framebuffer")
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

    def bind(self):
        gl = api()
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.id)
        gl.glViewport(0, 0, *self.texture.size)

    def close(self):
        api().glDeleteFramebuffers(1, [self.id])
        self.texture.close()
