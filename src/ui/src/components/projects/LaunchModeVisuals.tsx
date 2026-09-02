import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export type LaunchModeKind = 'copilot' | 'autonomous'

export const LAUNCH_DIALOG_SHELL_CLASS =
  'h-[90svh] w-[96vw] max-w-none rounded-[32px] border border-white/10 bg-[#091329]/98 shadow-[0_40px_120px_-52px_rgba(15,23,42,0.85)] lg:w-[88vw]'

function launchModeWash(mode: LaunchModeKind) {
  if (mode === 'copilot') {
    return {
      surface:
        'linear-gradient(135deg, rgba(13,28,57,0.98) 0%, rgba(18,39,78,0.98) 45%, rgba(39,45,99,0.98) 100%)',

      mistA: 'rgba(103,232,249,0.16)',
      mistB: 'rgba(96,165,250,0.14)',
      mistC: 'rgba(129,140,248,0.16)',

      vein: 'rgba(125,211,252,0.12)',
      grain: 'rgba(255,255,255,0.025)',
    }
  }

  return {
    surface:
      'linear-gradient(135deg, rgba(11,24,50,0.98) 0%, rgba(25,37,82,0.98) 45%, rgba(64,43,122,0.98) 100%)',

    mistA: 'rgba(96,165,250,0.14)',
    mistB: 'rgba(129,140,248,0.18)',
    mistC: 'rgba(167,139,250,0.18)',

    vein: 'rgba(167,139,250,0.12)',
    grain: 'rgba(255,255,255,0.025)',
  }
}

export function LaunchModeIllustration({
  mode,
  className,
}: {
  mode: LaunchModeKind
  className?: string
}) {
  const wash = launchModeWash(mode)

  return (
    <div
      className={cn(
        'relative aspect-[12/8] w-full overflow-hidden rounded-[28px] border border-white/[0.08]',
        className
      )}
      style={{
        backgroundImage: wash.surface,
      }}
    >
      {/* 蓝紫雾化光晕 */}
      <div
        className="absolute inset-0 opacity-90"
        style={{
          backgroundImage: [
            `radial-gradient(circle at 18% 24%, ${wash.mistA} 0%, transparent 30%)`,
            `radial-gradient(circle at 74% 22%, ${wash.mistB} 0%, transparent 28%)`,
            `radial-gradient(circle at 64% 74%, ${wash.mistC} 0%, transparent 30%)`,
            `radial-gradient(circle at 28% 72%, rgba(59,130,246,0.10) 0%, transparent 26%)`,
          ].join(','),
        }}
      />

      {/* 科研网络纹理 */}
      <div
        className="absolute inset-0 opacity-70"
        style={{
          backgroundImage: [
            `radial-gradient(ellipse at 16% 34%, ${wash.vein} 0%, transparent 42%)`,
            `radial-gradient(ellipse at 72% 30%, ${wash.vein} 0%, transparent 38%)`,
            `radial-gradient(ellipse at 58% 74%, ${wash.vein} 0%, transparent 34%)`,
            `repeating-linear-gradient(
              16deg,
              transparent 0 11px,
              ${wash.grain} 12px 13px,
              transparent 14px 24px
            )`,
            `repeating-linear-gradient(
              112deg,
              transparent 0 17px,
              ${wash.grain} 18px 19px,
              transparent 20px 32px
            )`,
          ].join(','),
        }}
      />

      {/* 冷色发光层 */}
      <div className="absolute -left-[8%] top-[8%] h-[54%] w-[46%] rounded-full bg-cyan-400/[0.08] blur-3xl" />

      <div className="absolute right-[-6%] top-[18%] h-[46%] w-[40%] rounded-full bg-indigo-400/[0.10] blur-3xl" />

      <div className="absolute bottom-[-10%] left-[28%] h-[40%] w-[48%] rounded-full bg-violet-500/[0.10] blur-3xl" />

      {/* 细网格 */}
      <div
        className="absolute inset-0 opacity-[0.12]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(148,163,184,0.18) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.18) 1px, transparent 1px)',
          backgroundSize: '32px 32px',
        }}
      />

      {/* 顶部高光 */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-200/40 to-transparent" />

      {/* 底部暗角 */}
      <div className="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-[#071126]/40 to-transparent" />
    </div>
  )
}

export function LaunchModeSummaryCard({
  mode,
  title,
  subtitle,
  keywords,
  badge,
  className,
}: {
  mode: LaunchModeKind
  title: string
  subtitle: string
  keywords: string[]
  badge?: ReactNode
  className?: string
}) {
  const tone =
    mode === 'copilot'
      ? {
          frame:
            'bg-[linear-gradient(145deg,rgba(15,30,61,0.98),rgba(18,38,75,0.96))]',

          chip:
            'border-cyan-300/15 bg-cyan-400/[0.07] text-cyan-100',
        }
      : {
          frame:
            'bg-[linear-gradient(145deg,rgba(15,29,60,0.98),rgba(37,32,83,0.96))]',

          chip:
            'border-violet-300/15 bg-violet-400/[0.08] text-violet-100',
        }

  return (
    <div
      className={cn(
        'rounded-[20px] border border-white/[0.08] bg-[#0B1730]/95 p-3.5 shadow-[0_24px_70px_-40px_rgba(0,0,0,0.85)] backdrop-blur-xl',
        className
      )}
    >
      <div
        className={cn(
          'relative overflow-hidden rounded-[16px] border border-white/[0.07] p-3',
          tone.frame
        )}
      >
        {/* badge */}
        {badge ? (
          <div className="absolute right-3 top-3 z-10">
            {badge}
          </div>
        ) : null}

        <LaunchModeIllustration
          mode={mode}
          className="mx-auto max-w-[320px]"
        />
      </div>

      <div className="mt-3.5">
        {/* 标题 */}
        <div className="text-[18px] font-semibold tracking-[-0.03em] text-slate-50">
          {title}
        </div>

        {/* 副标题 */}
        <div className="mt-1.5 text-sm leading-6 text-slate-400">
          {subtitle}
        </div>

        {/* 标签 */}
        <div className="mt-3 flex flex-wrap gap-2">
          {keywords.slice(0, 2).map((keyword) => (
            <span
              key={`${mode}-${keyword}`}
              className={cn(
                'rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-[0.16em]',
                tone.chip
              )}
            >
              {keyword}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}