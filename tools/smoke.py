#!/usr/bin/env python3
"""Standalone Pi smoke test: apt packages only; no visualz installation required."""

import argparse
import glob
import os
import time


def devices():
    try:
        import alsaaudio

        names = alsaaudio.pcms(alsaaudio.PCM_CAPTURE)
        print("ALSA capture devices:", ", ".join(names) or "none")
        for name in names:
            pcm = None
            try:
                pcm = alsaaudio.PCM(
                    type=alsaaudio.PCM_CAPTURE, mode=alsaaudio.PCM_NONBLOCK, device=name
                )
                info = pcm.info() if hasattr(pcm, "info") else {"channels": pcm.setchannels(2)}
                print(f"  {name}: configured channels {info.get('channels', 'unknown')}; {info}")
            except Exception as exc:
                print(f"  {name}: could not inspect channel count: {exc}")
            finally:
                if pcm:
                    pcm.close()
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
        program = gl.glCreateProgram()
        sources = [
            (
                gl.GL_VERTEX_SHADER,
                "attribute vec2 p; varying vec2 uv; void main(){uv=p;gl_Position=vec4(p,0.,1.);}",
            ),
            (
                gl.GL_FRAGMENT_SHADER,
                "precision mediump float; varying vec2 uv; "
                "uniform float t; void main(){gl_FragColor=vec4(.5+.5*cos("
                "t+uv.xyx*5.+vec3(0.,2.,4.)),1.);}",
            ),
        ]
        for kind, source in sources:
            shader = gl.glCreateShader(kind)
            gl.glShaderSource(shader, source)
            gl.glCompileShader(shader)
            if not gl.glGetShaderiv(shader, gl.GL_COMPILE_STATUS):
                raise RuntimeError(f"Shader failed: {gl.glGetShaderInfoLog(shader)}")
            gl.glAttachShader(program, shader)
            gl.glDeleteShader(shader)
        gl.glLinkProgram(program)
        if not gl.glGetProgramiv(program, gl.GL_LINK_STATUS):
            raise RuntimeError(f"Link failed: {gl.glGetProgramInfoLog(program)}")
        gl.glUseProgram(program)
        vertices = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="float32")
        buffer = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, buffer)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)
        location = gl.glGetAttribLocation(program, "p")
        gl.glEnableVertexAttribArray(location)
        gl.glVertexAttribPointer(location, 2, gl.GL_FLOAT, False, 0, c_void_p(0))
        gl.glViewport(0, 0, 1280, 720)
        start = time.monotonic()
        frames = 0
        while time.monotonic() - start < seconds:
            if any(e.type == pygame.QUIT for e in pygame.event.get()):
                break
            gl.glUniform1f(gl.glGetUniformLocation(program, "t"), time.monotonic() - start)
            gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
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
