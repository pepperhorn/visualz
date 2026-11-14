#!/usr/bin/env python3
"""Standalone Pi smoke test: apt packages only; no visualz installation required."""

import argparse
import glob
import os
import time
import re
from pathlib import Path


def capture_channels(proc_root="/proc/asound"):
    """Read actual USB capture channel counts, never the configured PCM width."""
    result = {}
    for path in Path(proc_root).glob("card*/stream*"):
        capture = False
        counts = set()
        for line in path.read_text(errors="replace").splitlines():
            section = re.match(r"^\s*(Playback|Capture):", line)
            if section:
                capture = section[1] == "Capture"
            channel = re.search(r"Channels:\s*(\d+)", line)
            if capture and channel:
                counts.add(int(channel[1]))
        if counts:
            result[str(path)] = sorted(counts)
    return result


def devices():
    try:
        counts = capture_channels()
        print(
            "USB capture hardware channels:",
            counts or "unavailable (no USB capture stream descriptors)",
        )
        import alsaaudio

        names = alsaaudio.pcms(alsaaudio.PCM_CAPTURE)
        print("ALSA capture device names:", ", ".join(names) or "none")
        print(
            "Counts above are from USB Capture descriptors; non-USB / plugin channel limits are unknown."
        )
    except Exception as exc:
        print(f"ALSA enumeration failed (install python3-alsaaudio): {exc}")
    video = glob.glob("/dev/video*")
    print("Video capture candidates:", ", ".join(video) or "none")
    for device in video:
        try:
            import subprocess

            result = subprocess.run(
                ["v4l2-ctl", "-d", device, "--all"], capture_output=True, text=True, timeout=5
            )
            if result.returncode:
                print(f"  {device}: cannot inspect: {result.stderr.strip()}")
            else:
                print(f"  {device}:\n{result.stdout}")
        except Exception as exc:
            print(f"  {device}: enumeration failed (install v4l-utils): {exc}")


def display(window, seconds):
    pygame = None
    try:
        if not window:
            os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
            os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
        import pygame
        import numpy as np
        from ctypes import c_void_p
        from OpenGL import GLES2 as gl

        pygame.display.init()
        pygame.display.gl_set_attribute(
            pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES
        )
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 2)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 0)
        flags = pygame.OPENGL | pygame.DOUBLEBUF | (0 if window else pygame.FULLSCREEN)
        pygame.display.set_mode((1280, 720), flags)
        for name in ("VENDOR", "RENDERER", "VERSION"):
            # GLES2 returns a GLubyte pointer; cast for readable driver strings.
            import ctypes

            pointer = gl.glGetString(getattr(gl, "GL_" + name))
            value = ctypes.cast(pointer, ctypes.c_char_p).value
            print(f"GL {name}: {value.decode() if value else 'unknown'}")
        print("GL maximum texture size:", int(gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE)))
        from OpenGL import platform

        print("PyOpenGL platform:", type(platform.PLATFORM).__name__)
        for kind in ("HIGH_FLOAT", "MEDIUM_FLOAT"):
            limits = (ctypes.c_int * 2)()
            precision = ctypes.c_int()
            gl.glGetShaderPrecisionFormat(
                gl.GL_FRAGMENT_SHADER, getattr(gl, "GL_" + kind), limits, ctypes.byref(precision)
            )
            print(f"Fragment {kind}: range={list(limits)}, precision={precision.value}")

        def program(fragment):
            result = gl.glCreateProgram()
            for kind, source in [
                (
                    gl.GL_VERTEX_SHADER,
                    "attribute vec2 p; varying vec2 uv; void main(){uv=(p+1.)*.5;gl_Position=vec4(p,0.,1.);}",
                ),
                (gl.GL_FRAGMENT_SHADER, fragment),
            ]:
                shader = gl.glCreateShader(kind)
                gl.glShaderSource(shader, source)
                gl.glCompileShader(shader)
                if not gl.glGetShaderiv(shader, gl.GL_COMPILE_STATUS):
                    raise RuntimeError(f"Shader failed: {gl.glGetShaderInfoLog(shader)}")
                gl.glAttachShader(result, shader)
                gl.glDeleteShader(shader)
            gl.glLinkProgram(result)
            if not gl.glGetProgramiv(result, gl.GL_LINK_STATUS):
                raise RuntimeError(f"Link failed: {gl.glGetProgramInfoLog(result)}")
            return result

        animated = program(
            "precision mediump float; varying vec2 uv; uniform sampler2D image; uniform float t; void main(){gl_FragColor=vec4(.5+.5*cos(t+uv.xyx*5.+vec3(0.,2.,4.)),1.)*texture2D(image,uv);}"
        )
        screen = program(
            "precision mediump float; varying vec2 uv; uniform sampler2D image; void main(){gl_FragColor=texture2D(image,uv);}"
        )

        def texture(width, height, pixels=None):
            result = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, result)
            for key in (gl.GL_TEXTURE_MIN_FILTER, gl.GL_TEXTURE_MAG_FILTER):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, key, gl.GL_LINEAR)
            for key in (gl.GL_TEXTURE_WRAP_S, gl.GL_TEXTURE_WRAP_T):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, key, gl.GL_CLAMP_TO_EDGE)
            gl.glTexImage2D(
                gl.GL_TEXTURE_2D,
                0,
                gl.GL_RGBA,
                width,
                height,
                0,
                gl.GL_RGBA,
                gl.GL_UNSIGNED_BYTE,
                pixels,
            )
            return result

        uploaded = texture(16, 16, np.full((16, 16, 4), 255, dtype=np.uint8))
        target = texture(480, 270)
        fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, fbo)
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D, target, 0
        )
        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("NPOT 480x270 framebuffer is incomplete")
        print("Texture upload and NPOT 480x270 FBO: ready; sampling at 1280x720")
        vertices = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="float32")
        buffer = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, buffer)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)

        def draw(prog, source, width, height):
            gl.glViewport(0, 0, width, height)
            gl.glUseProgram(prog)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, source)
            gl.glUniform1i(gl.glGetUniformLocation(prog, "image"), 0)
            location = gl.glGetAttribLocation(prog, "p")
            gl.glEnableVertexAttribArray(location)
            gl.glVertexAttribPointer(location, 2, gl.GL_FLOAT, False, 0, c_void_p(0))
            gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
            gl.glDisableVertexAttribArray(location)

        start = time.monotonic()
        frames = 0
        while time.monotonic() - start < seconds:
            if any(e.type == pygame.QUIT for e in pygame.event.get()):
                break
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, fbo)
            gl.glUseProgram(animated)
            gl.glUniform1f(gl.glGetUniformLocation(animated, "t"), time.monotonic() - start)
            draw(animated, uploaded, 480, 270)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
            draw(screen, target, 1280, 720)
            pygame.display.flip()
            frames += 1
        print(f"Display: {frames / max(0.001, time.monotonic() - start):.1f} fps ({frames} frames)")
        return True
    except Exception as exc:
        print(f"Display smoke test failed: {exc}")
        print(
            "Check python3-pygame, python3-opengl, python3-numpy, KMS/DRM support, "
            "HDMI connection and video/render/input group permissions."
        )
        return False
    finally:
        if pygame:
            pygame.display.quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", action="store_true", help="Test desktop instead of KMS/DRM")
    parser.add_argument("--seconds", type=float, default=15, help="Animation duration (default 15)")
    args = parser.parse_args()
    devices()
    return 0 if display(args.window, max(0.1, args.seconds)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
