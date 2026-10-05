'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import {
  ArrowLeftIcon,
  AtomIcon,
  BookIcon,
  CloseIcon,
  GlobeIcon,
  HistoryIcon,
  SparkIcon,
} from '@/components/ui/Icon'
import { PhysicsChatView } from './PhysicsChatView'

type SubjectKey = 'physics' | 'mathematics' | 'chemistry' | 'english' | 'urdu' | 'islamiyat'

type Props = {
  isOpen: boolean
  onClose: () => void
}

export function SubjectModal({ isOpen, onClose }: Props) {
  const tModal = useTranslations('tutor.modal')
  const tSubs = useTranslations('tutor.subjects')
  const [stage, setStage] = useState<'select' | 'coming-soon' | 'physics'>('select')
  const [selectedSubject, setSelectedSubject] = useState<SubjectKey | null>(null)

  if (!isOpen) return null

  const subjects: Array<{
    key: SubjectKey
    available: boolean
    icon: typeof AtomIcon
    accent: string
  }> = [
    {
      key: 'physics',
      available: true,
      icon: AtomIcon,
      accent: 'bg-primary-container text-on-primary',
    },
    {
      key: 'mathematics',
      available: false,
      icon: SparkIcon,
      accent: 'bg-secondary-container text-on-secondary-container',
    },
    {
      key: 'chemistry',
      available: false,
      icon: SparkIcon,
      accent: 'bg-tertiary-container text-on-tertiary',
    },
    {
      key: 'english',
      available: false,
      icon: GlobeIcon,
      accent: 'bg-surface-container-high text-on-surface',
    },
    {
      key: 'urdu',
      available: false,
      icon: BookIcon,
      accent: 'bg-surface-container-high text-on-surface',
    },
    {
      key: 'islamiyat',
      available: false,
      icon: BookIcon,
      accent: 'bg-surface-container-high text-on-surface',
    },
  ]

  function handleSelect(sub: (typeof subjects)[0]) {
    if (sub.available) {
      setStage('physics')
    } else {
      setSelectedSubject(sub.key)
      setStage('coming-soon')
    }
  }

  function handleModalClose() {
    setStage('select')
    setSelectedSubject(null)
    onClose()
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="tutor-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
    >
      <div className="relative w-full max-w-2xl">
        {stage === 'physics' ? (
          <PhysicsChatView onBack={() => setStage('select')} onClose={handleModalClose} />
        ) : stage === 'coming-soon' ? (
          /* Non-Physics Coming Soon Dialogue */
          <div className="overflow-hidden rounded-xl border border-outline-variant/30 bg-surface-container-lowest p-6 shadow-2xl sm:p-8">
            <div className="flex items-center justify-between">
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary-fixed text-primary">
                <HistoryIcon className="h-6 w-6" />
              </span>
              <button
                type="button"
                onClick={handleModalClose}
                aria-label={tModal('close')}
                className="flex h-9 w-9 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-variant"
              >
                <CloseIcon className="h-5 w-5" />
              </button>
            </div>

            <div className="mt-4 space-y-2 text-start">
              <h3
                id="tutor-modal-title"
                className="text-headline-sm font-headline font-bold text-on-surface"
              >
                {tModal('comingSoonTitle')}
              </h3>
              <p className="text-body-md text-on-surface-variant">
                {tModal('comingSoonNotice', {
                  subject: selectedSubject ? tSubs(selectedSubject) : '',
                })}
              </p>
            </div>

            <div className="mt-6 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => setStage('select')}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-body-md font-semibold text-on-primary transition-colors hover:bg-primary-container"
              >
                <ArrowLeftIcon className="h-4 w-4 rtl:-scale-x-100" />
                <span>{tModal('back')}</span>
              </button>
              <button
                type="button"
                onClick={handleModalClose}
                className="rounded-lg border border-outline px-5 py-2.5 text-body-md font-semibold text-on-surface transition-colors hover:bg-surface-container-high"
              >
                {tModal('close')}
              </button>
            </div>
          </div>
        ) : (
          /* Subject Selection Picker */
          <div className="overflow-hidden rounded-xl border border-outline-variant/30 bg-surface-container-lowest p-6 shadow-2xl sm:p-8">
            <div className="flex items-start justify-between">
              <div className="space-y-1 text-start">
                <h3
                  id="tutor-modal-title"
                  className="font-headline text-headline-md font-bold text-on-surface"
                >
                  {tModal('title')}
                </h3>
                <p className="text-body-sm text-on-surface-variant">{tModal('subtitle')}</p>
              </div>
              <button
                type="button"
                onClick={handleModalClose}
                aria-label={tModal('close')}
                className="flex h-9 w-9 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-variant"
              >
                <CloseIcon className="h-5 w-5" />
              </button>
            </div>

            <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
              {subjects.map((sub) => {
                const Icon = sub.icon
                return (
                  <button
                    key={sub.key}
                    type="button"
                    onClick={() => handleSelect(sub)}
                    className={`group relative flex items-center justify-between rounded-xl border p-4 text-start transition-all hover:scale-[1.01] hover:shadow-md ${
                      sub.available
                        ? 'border-primary/40 bg-surface-container-low hover:border-primary'
                        : 'border-outline-variant/40 bg-surface-container-lowest hover:border-outline'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className={`flex h-10 w-10 items-center justify-center rounded-lg shadow-sm ${sub.accent}`}
                      >
                        <Icon className="h-5 w-5" />
                      </span>
                      <div>
                        <p className="text-title-md font-headline font-semibold text-on-surface">
                          {tSubs(sub.key)}
                        </p>
                        <p className="text-xs text-on-surface-variant">PCTB · Class 9</p>
                      </div>
                    </div>

                    <span
                      className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                        sub.available
                          ? 'bg-primary-container text-on-primary'
                          : 'bg-surface-variant text-on-surface-variant'
                      }`}
                    >
                      {sub.available ? tModal('availableBadge') : tModal('comingSoonBadge')}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
