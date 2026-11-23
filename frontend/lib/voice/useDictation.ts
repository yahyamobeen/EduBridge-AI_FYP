'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { transcribeAudio } from '@/lib/api/endpoints'
import { stopSpeech } from './useSpeech'

export type DictationState = 'idle' | 'recording' | 'processing'

type Options = {
  /** `ur` forces Urdu; `en` forces English; omitted lets Whisper detect. */
  languageHint?: 'ur' | 'en'
  /** `arabic` keeps Urdu script; `latin` transliterates it to Roman Urdu. */
  targetScript?: 'arabic' | 'latin'
  onTranscript: (text: string) => void
  onError: (message: string) => void
  messages: { unsupported: string; denied: string; failed: string }
}

/**
 * Record a short clip and transcribe it with the backend's Whisper route.
 *
 * Deliberately simpler than the tutor's richer path (which adds browser-native
 * recognition for English): the class chat has no language selector, so the
 * caller passes the page locale and Whisper does the work. Starting a recording
 * always stops any speech that is playing — one audio channel at a time.
 */
export function useDictation({
  languageHint,
  targetScript,
  onTranscript,
  onError,
  messages,
}: Options) {
  const [state, setState] = useState<DictationState>('idle')
  const [audioLevel, setAudioLevel] = useState(0)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const ctxRef = useRef<AudioContext | null>(null)
  const rafRef = useRef<number | null>(null)

  // Latest values, so the callbacks stay stable across renders.
  const onTranscriptRef = useRef(onTranscript)
  onTranscriptRef.current = onTranscript
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError
  const messagesRef = useRef(messages)
  messagesRef.current = messages
  const hintRef = useRef(languageHint)
  hintRef.current = languageHint
  const scriptRef = useRef(targetScript)
  scriptRef.current = targetScript

  const stopMeter = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    if (ctxRef.current) {
      ctxRef.current.close().catch(() => {})
      ctxRef.current = null
    }
    setAudioLevel(0)
  }, [])

  const cleanup = useCallback(() => {
    stopMeter()
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    recorderRef.current = null
    chunksRef.current = []
  }, [stopMeter])

  const stop = useCallback(() => {
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      // `onstop` finishes the job.
      recorder.stop()
    } else {
      cleanup()
      setState('idle')
    }
  }, [cleanup])

  const start = useCallback(async () => {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      onErrorRef.current(messagesRef.current.unsupported)
      return
    }
    if (typeof MediaRecorder === 'undefined') {
      onErrorRef.current(messagesRef.current.unsupported)
      return
    }

    // One audio channel: recording silences the speaker.
    stopSpeech()
    setState('recording')
    chunksRef.current = []

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setState('idle')
      onErrorRef.current(messagesRef.current.denied)
      return
    }
    streamRef.current = stream

    // Cosmetic level meter; a failure here must not stop the recording.
    try {
      const ctx = new (window.AudioContext || (window as any).webkitAudioContext)()
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 64
      ctx.createMediaStreamSource(stream).connect(analyser)
      ctxRef.current = ctx
      const data = new Uint8Array(analyser.frequencyBinCount)
      const tick = () => {
        analyser.getByteFrequencyData(data)
        const avg = data.reduce((a, b) => a + b, 0) / data.length
        setAudioLevel(avg / 255)
        rafRef.current = requestAnimationFrame(tick)
      }
      tick()
    } catch {
      // no meter
    }

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : ''
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data)
    }
    recorder.onstop = async () => {
      const blob = new Blob(chunksRef.current, { type: mimeType || 'audio/webm' })
      cleanup()
      setState('processing')
      try {
        const res = await transcribeAudio(blob, hintRef.current, scriptRef.current)
        if (res.transcript) onTranscriptRef.current(res.transcript)
      } catch {
        onErrorRef.current(messagesRef.current.failed)
      } finally {
        setState('idle')
      }
    }
    recorderRef.current = recorder
    recorder.start(250)
  }, [cleanup])

  const toggle = useCallback(() => {
    if (state === 'recording') stop()
    else if (state === 'idle') void start()
  }, [state, start, stop])

  // Stop the microphone and meter if the component goes away mid-recording.
  useEffect(() => cleanup, [cleanup])

  return { state, audioLevel, toggle, stop }
}
