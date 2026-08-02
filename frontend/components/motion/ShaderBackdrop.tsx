'use client'

import { useEffect, useRef, useState } from 'react'

const VERTEX_SHADER = `
attribute vec2 a_position;
void main() { gl_Position = vec4(a_position, 0.0, 1.0); }
`

/** The prototype's shader: two slow sine waves tinting a near-white field. */
const FRAGMENT_SHADER = `
precision mediump float;
uniform float u_time;
uniform vec2 u_res;
void main() {
  vec2 uv = gl_FragCoord.xy / u_res;
  float shade = 0.0;
  shade += sin(uv.x * 10.0 + u_time) * 0.1;
  shade += sin(uv.y * 15.0 + u_time * 0.5) * 0.1;
  gl_FragColor = vec4(0.97, 0.98, 1.0, 0.2 + shade);
}
`

function compile(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type)
  if (shader === null) return null
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader)
    return null
  }
  return shader
}

/**
 * Animated hero backdrop from the prototype.
 *
 * Three things it will not do, each for a reason rather than to simplify:
 *
 *  - It does not run under `prefers-reduced-motion`.
 *  - It stops rendering when the tab is hidden, so a backgrounded tab is not
 *    burning a phone battery on an invisible animation.
 *  - It falls back to a CSS gradient when WebGL is missing or the shaders fail
 *    to compile, which is realistic on the entry-level Android devices in
 *    prd.md 3.1.
 *
 * Purely decorative, so it is hidden from assistive technology.
 */
export function ShaderBackdrop() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [active, setActive] = useState(false)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    const canvas = canvasRef.current
    if (canvas === null) return

    const gl = canvas.getContext('webgl', { antialias: false, alpha: true })
    if (gl === null) return

    const vs = compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER)
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER)
    const program = gl.createProgram()
    if (vs === null || fs === null || program === null) return

    gl.attachShader(program, vs)
    gl.attachShader(program, fs)
    gl.linkProgram(program)
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return
    gl.useProgram(program)

    const buffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW,
    )
    const positionLocation = gl.getAttribLocation(program, 'a_position')
    gl.enableVertexAttribArray(positionLocation)
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0)

    const timeLocation = gl.getUniformLocation(program, 'u_time')
    const resolutionLocation = gl.getUniformLocation(program, 'u_res')

    // Cap the backing store: a full-resolution buffer on a high-DPI phone is
    // a lot of fragments for a soft gradient nobody looks at directly.
    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5)
      canvas.width = Math.floor(canvas.clientWidth * ratio)
      canvas.height = Math.floor(canvas.clientHeight * ratio)
      gl.viewport(0, 0, canvas.width, canvas.height)
    }
    resize()
    window.addEventListener('resize', resize, { passive: true })

    setActive(true)

    let frame = 0
    let running = true

    const render = (now: number) => {
      if (!running) return
      gl.uniform1f(timeLocation, now * 0.001)
      gl.uniform2f(resolutionLocation, canvas.width, canvas.height)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      frame = window.requestAnimationFrame(render)
    }
    frame = window.requestAnimationFrame(render)

    const onVisibility = () => {
      if (document.hidden) {
        running = false
        window.cancelAnimationFrame(frame)
      } else if (!running) {
        running = true
        frame = window.requestAnimationFrame(render)
      }
    }
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      running = false
      window.cancelAnimationFrame(frame)
      window.removeEventListener('resize', resize)
      document.removeEventListener('visibilitychange', onVisibility)
      gl.deleteProgram(program)
      gl.deleteShader(vs)
      gl.deleteShader(fs)
      gl.deleteBuffer(buffer)
    }
  }, [])

  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
      {/* Always rendered: this is the whole backdrop when the shader is off. */}
      <div className="absolute inset-0 bg-gradient-to-br from-primary-fixed/50 via-surface to-secondary-fixed/30" />
      <div className="absolute -start-24 -top-24 h-72 w-72 rounded-full bg-primary-fixed-dim/30 blur-3xl motion-safe:animate-drift-slow" />
      <div className="absolute -bottom-32 -end-16 h-80 w-80 rounded-full bg-secondary-fixed/30 blur-3xl motion-safe:animate-drift-slower" />
      <div className="dot-pattern absolute inset-0 opacity-60" />
      <canvas
        ref={canvasRef}
        className={`absolute inset-0 h-full w-full transition-opacity duration-700 ${
          active ? 'opacity-100' : 'opacity-0'
        }`}
      />
      <div className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-background to-transparent" />
    </div>
  )
}
