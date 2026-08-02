'use client'

import { useEffect } from 'react'

/**
 * Scroll reveal, from the landing prototype.
 *
 * Two deliberate details:
 *
 *  - The hidden-until-revealed CSS is scoped behind `data-reveal-ready`, which
 *    this component sets on mount. Without that, a visitor whose JavaScript
 *    fails would be served a page whose content is permanently `opacity: 0` --
 *    an invisible page is a worse failure than an unanimated one.
 *
 *  - Elements are unobserved once shown, so scrolling back up does not replay
 *    the animation and the observer stops doing work.
 */
export function RevealController() {
  useEffect(() => {
    const root = document.documentElement
    const targets = document.querySelectorAll<HTMLElement>('.reveal, .stagger')

    if (typeof IntersectionObserver === 'undefined') {
      targets.forEach((el) => el.classList.add('is-visible'))
      return
    }

    root.setAttribute('data-reveal-ready', 'true')

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          entry.target.classList.add('is-visible')
          observer.unobserve(entry.target)
        }
      },
      // Fires slightly before the element is fully on screen, so the motion
      // reads as the section arriving rather than catching up.
      { threshold: 0.12, rootMargin: '0px 0px -40px 0px' },
    )

    targets.forEach((el) => observer.observe(el))

    return () => {
      observer.disconnect()
      root.removeAttribute('data-reveal-ready')
    }
  }, [])

  return null
}

/**
 * Parallax drift on scroll. Reads once per frame and writes a CSS variable,
 * so the scroll handler itself stays cheap; skipped entirely under reduced
 * motion.
 */
export function ParallaxController() {
  useEffect(() => {
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (prefersReduced.matches) return

    const targets = Array.from(document.querySelectorAll<HTMLElement>('[data-parallax-speed]'))
    if (targets.length === 0) return

    let frame = 0

    const apply = () => {
      frame = 0
      const scrolled = window.scrollY
      for (const el of targets) {
        const speed = Number.parseFloat(el.dataset.parallaxSpeed ?? '0.05')
        el.style.setProperty('--parallax-offset', `${scrolled * speed}px`)
      }
    }

    const onScroll = () => {
      if (frame !== 0) return
      frame = window.requestAnimationFrame(apply)
    }

    apply()
    window.addEventListener('scroll', onScroll, { passive: true })

    return () => {
      window.removeEventListener('scroll', onScroll)
      if (frame !== 0) window.cancelAnimationFrame(frame)
    }
  }, [])

  return null
}
