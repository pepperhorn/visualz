"""T2 seam: ES 1.00 animated test pattern in place of the visual engine."""

from visualz.gl import Program, Quad, api

PATTERN = """precision mediump float;
varying vec2 uv; uniform float time;
void main(){gl_FragColor=vec4(0.5+0.5*cos(time+uv.xyx*6.0+vec3(0.,2.,4.)),1.);}"""


class Engine:
    """Engine(context, store, audio, camera): GL-owned resources on main thread.

    draw(state, audio_frame, now) draws visuals into default framebuffer; state is
    immutable, audio_frame is Analyser.snapshot(), now monotonic seconds. No swap,
    disk reads or waiting on workers. close() releases GPU resources.
    """

    def __init__(self, context, store, audio, camera):
        self.context, self.store, self.audio, self.camera = context, store, audio, camera
        self.program, self.quad = Program(PATTERN), Quad()
        store.runtime.register_command("gallery", "next", self.next)
        store.runtime.register_command("gallery", "prev", self.prev)

    def draw(self, state, audio_frame, now):
        gl = api()
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        gl.glViewport(0, 0, *self.context.size)
        self.program.use(time=now % 10000)
        self.quad.draw(self.program)
        if state["settings"]["blackout"]["enabled"]:
            gl.glClearColor(0, 0, 0, 1)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)

    def close(self):
        self.quad.close()
        self.program.close()

    def next(self):
        """T2: request the next gallery source without waiting for decoding."""
        pass

    def prev(self):
        """T2: request the previous gallery source without waiting for decoding."""
        pass
