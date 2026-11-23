'use client'

import { PauseIcon, PlayIcon, StopIcon, VolumeIcon } from '@/components/ui/Icon'
import { pauseSpeech, resumeSpeech, speak, stopSpeech, useSpeech } from '@/lib/voice/useSpeech'

type Props = {
  /**
   * Stable identity for this speaker. The message id is ideal: it lets the
   * shared player show "playing" on exactly one message, never two.
   */
  id: string
  /** The generated text to read aloud — never the student's own input. */
  text: string
  /** Reply language: `en`, `ur`, or `ur-Latn` (Roman Urdu). */
  language?: string
  /** `female` or `male`; selects the Urdu/English voice. */
  gender?: string
  labels: { speak: string; stop: string; pause: string; resume: string }
  className?: string
}

/**
 * A speaker control for one message. Idle → speak, loading → cancel, playing →
 * pause, paused → resume; a separate stop button ends playback. Every instance
 * shares one audio element, so pressing any of them stops the last clip.
 */
export function SpeakButton({ id, text, language, gender, labels, className = '' }: Props) {
  const speech = useSpeech()
  const active = speech.id === id
  const status = active ? speech.status : 'idle'

  const buttonClass =
    'inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-outline bg-surface text-on-surface transition-colors hover:border-primary hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50'

  function onPrimary() {
    if (status === 'idle') {
      void speak({ id, text, language, gender })
    } else if (status === 'loading') {
      stopSpeech()
    } else if (status === 'playing') {
      pauseSpeech()
    } else {
      resumeSpeech()
    }
  }

  const primaryLabel =
    status === 'loading'
      ? labels.stop
      : status === 'playing'
        ? labels.pause
        : status === 'paused'
          ? labels.resume
          : labels.speak

  return (
    <span className={`inline-flex items-center gap-1 ${className}`}>
      <button
        type="button"
        onClick={onPrimary}
        aria-label={primaryLabel}
        aria-pressed={active && status !== 'idle'}
        title={primaryLabel}
        className={buttonClass}
      >
        {status === 'loading' ? (
          <span
            className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
            aria-hidden="true"
          />
        ) : status === 'playing' ? (
          <PauseIcon className="h-5 w-5" />
        ) : status === 'paused' ? (
          <PlayIcon className="h-5 w-5" />
        ) : (
          <VolumeIcon className="h-5 w-5" />
        )}
      </button>

      {active && status !== 'idle' && (
        <button
          type="button"
          onClick={stopSpeech}
          aria-label={labels.stop}
          title={labels.stop}
          className={buttonClass}
        >
          <StopIcon className="h-4 w-4" />
        </button>
      )}
    </span>
  )
}
