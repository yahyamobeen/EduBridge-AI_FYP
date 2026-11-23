'use client'

import { useSyncExternalStore } from 'react'
import { speakText } from '@/lib/api/endpoints'

/**
 * One audio element for the whole application.
 *
 * Every speaker button on every chat surface goes through this module, so
 * exactly one clip can play at a time: starting a new one stops the old one and
 * aborts its in-flight synthesis request. The state lives outside React so a
 * message that re-renders (or a list that virtualises) cannot leave a second
 * `Audio` playing behind it.
 */
export type SpeechStatus = 'idle' | 'loading' | 'playing' | 'paused'

export type SpeechState = {
  /** The control that owns the current clip, or null when nothing is active. */
  id: string | null
  status: SpeechStatus
}

const IDLE: SpeechState = { id: null, status: 'idle' }

let state: SpeechState = IDLE
let audio: HTMLAudioElement | null = null
let objectUrl: string | null = null
let abort: AbortController | null = null
/**
 * Monotonic token. A request that finishes after being superseded (a newer
 * speaker was pressed, or the clip was stopped) compares its captured value
 * against this and discards its result instead of starting a second clip.
 */
let token = 0

const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

function setState(next: SpeechState) {
  state = next
  emit()
}

function releaseAudio() {
  if (audio) {
    audio.onended = null
    audio.onerror = null
    audio.pause()
    audio = null
  }
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
    objectUrl = null
  }
}

/** Stop whatever is playing and abort any synthesis still in flight. */
export function stopSpeech() {
  token += 1
  if (abort) {
    abort.abort()
    abort = null
  }
  releaseAudio()
  if (state.status !== 'idle' || state.id !== null) setState(IDLE)
}

export function pauseSpeech() {
  if (audio && state.status === 'playing') {
    audio.pause()
    setState({ ...state, status: 'paused' })
  }
}

export function resumeSpeech() {
  if (audio && state.status === 'paused') {
    void audio.play()
    setState({ ...state, status: 'playing' })
  }
}

/**
 * Synthesize `text` and play it, replacing whatever was playing.
 *
 * `language` is the tutor's reply language (`en` / `ur` / `ur-Latn`); the
 * backend converts Roman Urdu to Urdu script and picks the matching voice.
 */
export async function speak(opts: {
  id: string
  text: string
  language?: string
  gender?: string
}): Promise<void> {
  const text = opts.text.trim()
  if (!text) return

  // One audio at a time: stop the previous clip and abort its request.
  stopSpeech()
  const mine = token
  setState({ id: opts.id, status: 'loading' })

  const controller = new AbortController()
  abort = controller
  try {
    const blob = await speakText(text, opts.language, opts.gender, controller.signal)
    if (mine !== token) return

    objectUrl = URL.createObjectURL(blob)
    const element = new Audio(objectUrl)
    audio = element
    element.onended = () => {
      if (mine === token) stopSpeech()
    }
    element.onerror = () => {
      if (mine === token) stopSpeech()
    }

    await element.play()
    if (mine !== token) {
      // A stop arrived while the browser was starting playback.
      releaseAudio()
      return
    }
    setState({ id: opts.id, status: 'playing' })
  } catch {
    if (mine === token) stopSpeech()
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function getSnapshot(): SpeechState {
  return state
}

const SERVER_SNAPSHOT: SpeechState = IDLE
function getServerSnapshot(): SpeechState {
  return SERVER_SNAPSHOT
}

/** Subscribe a component to the shared player's state. */
export function useSpeech(): SpeechState {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
