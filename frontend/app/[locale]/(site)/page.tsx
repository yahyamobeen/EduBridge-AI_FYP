import { setRequestLocale } from 'next-intl/server'
import { Capabilities } from '@/components/landing/Capabilities'
import { Hero } from '@/components/landing/Hero'
import { Solutions } from '@/components/landing/Solutions'
import { ParallaxController, RevealController } from '@/components/motion/Reveal'

type Props = { params: Promise<{ locale: string }> }

/**
 * Landing page. Static: no auth call, and the only client JavaScript is the
 * motion controllers and the shader backdrop, all of which no-op under reduced
 * motion and degrade to a static page if they fail (prd.md A11Y-1, A11Y-2).
 */
export default async function Page({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)

  return (
    <>
      <RevealController />
      <ParallaxController />
      <Hero />
      <Solutions />
      <Capabilities />
    </>
  )
}
