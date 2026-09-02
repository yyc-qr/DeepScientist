import { Clock3, Sparkles } from 'lucide-react'

import {
  resolveProjectAccent,
  resolveProjectBackgroundStyle,
  resolveProjectTemplate,
  type ProjectAccentId,
  type ProjectBackgroundStyleId,
  type ProjectTemplateId,
} from '@/lib/projectDisplayCatalog'
import { cn } from '@/lib/utils'

type ProjectDisplayPreviewCardProps = {
  title: string
  subtitle?: string | null
  template?: ProjectTemplateId | string | null
  accentColor?: ProjectAccentId | string | null
  backgroundStyle?: ProjectBackgroundStyleId | string | null
  meta?: string | null
  modeLabel?: string | null
  className?: string
}

export function ProjectDisplayPreviewCard({
  title,
  subtitle,
  template,
  accentColor,
  backgroundStyle,
  meta,
  modeLabel,
  className,
}: ProjectDisplayPreviewCardProps) {
  const accent = resolveProjectAccent(accentColor)
  const templateMeta = resolveProjectTemplate(template)
  const backgroundMeta = resolveProjectBackgroundStyle(backgroundStyle)

  const backgroundOverlayClassName =
    backgroundMeta.id === 'grid'
      ? 'bg-[linear-gradient(180deg,rgba(96,165,250,0.10),rgba(15,23,42,0.04)),linear-gradient(90deg,rgba(148,163,184,0.10)_1px,transparent_1px),linear-gradient(rgba(148,163,184,0.10)_1px,transparent_1px)] bg-[size:auto,24px_24px,24px_24px]'
      : backgroundMeta.id === 'archive'
        ? 'bg-[linear-gradient(180deg,rgba(129,140,248,0.08),rgba(15,23,42,0.02)),radial-gradient(circle_at_top_left,rgba(96,165,250,0.14),transparent_32%),linear-gradient(135deg,rgba(76,29,149,0.10),transparent_44%)]'
        : backgroundMeta.id === 'cloud'
          ? 'bg-[radial-gradient(circle_at_18%_20%,rgba(96,165,250,0.16),transparent_28%),radial-gradient(circle_at_74%_26%,rgba(129,140,248,0.14),transparent_24%),radial-gradient(circle_at_56%_78%,rgba(167,139,250,0.12),transparent_24%)]'
          : backgroundMeta.id === 'studio'
            ? 'bg-[linear-gradient(180deg,rgba(96,165,250,0.08),rgba(15,23,42,0.02)),linear-gradient(135deg,rgba(129,140,248,0.10),transparent_40%)]'
            : 'bg-[linear-gradient(180deg,rgba(96,165,250,0.10),rgba(15,23,42,0.03))]'

  const templateDecoration =
    templateMeta.id === 'experiment' ? (
      <div
        className="absolute inset-x-5 top-[72px] flex items-center gap-2 opacity-90"
        aria-hidden
      >
        <div className="h-2 w-2 rounded-full bg-cyan-200/90" />
        <div className="h-[2px] flex-1 rounded-full bg-blue-300/45" />
        <div className="h-2 w-2 rounded-full bg-indigo-200/80" />
        <div className="h-[2px] w-16 rounded-full bg-violet-300/35" />
      </div>
    ) : templateMeta.id === 'literature' ? (
      <div
        className="absolute right-5 top-[72px] w-24 space-y-2 opacity-85"
        aria-hidden
      >
        <div className="h-[3px] rounded-full bg-cyan-200/65" />
        <div className="h-[3px] w-4/5 rounded-full bg-blue-300/45" />
        <div className="h-[3px] w-3/5 rounded-full bg-indigo-300/35" />
      </div>
    ) : templateMeta.id === 'analysis' ? (
      <div
        className="absolute right-5 top-[66px] flex h-14 items-end gap-1.5 opacity-85"
        aria-hidden
      >
        <div
          className="w-3 rounded-t-full bg-blue-300/35"
          style={{ height: '36%' }}
        />
        <div
          className="w-3 rounded-t-full bg-indigo-300/50"
          style={{ height: '68%' }}
        />
        <div
          className="w-3 rounded-t-full bg-violet-300/70"
          style={{ height: '94%' }}
        />
      </div>
    ) : (
      <div
        className="absolute right-5 top-[70px] rounded-full border border-blue-300/25 bg-blue-400/[0.08] px-3 py-1 text-[10px] uppercase tracking-[0.16em] text-blue-100"
        aria-hidden
      >
        Ready
      </div>
    )

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-[28px] border border-blue-300/15 bg-[#0B1730]/95 p-5 shadow-[0_28px_90px_-52px_rgba(0,0,0,0.78)] backdrop-blur-xl',
        className
      )}
    >
      <div
        className={cn(
          'absolute inset-0 bg-gradient-to-br opacity-55',
          accent.previewClassName
        )}
        aria-hidden
      />

      <div
        className={cn(
          'absolute inset-0 opacity-45 mix-blend-screen',
          accent.washClassName
        )}
        aria-hidden
      />

      <div
        className={cn(
          'absolute inset-0 opacity-95',
          backgroundOverlayClassName
        )}
        aria-hidden
      />

      <div
        className="absolute inset-0 bg-[radial-gradient(circle_at_20%_12%,rgba(96,165,250,0.08),transparent_30%),radial-gradient(circle_at_86%_18%,rgba(139,92,246,0.10),transparent_30%),linear-gradient(180deg,rgba(7,17,38,0.02),rgba(7,17,38,0.28))]"
        aria-hidden
      />

      <div className="absolute right-5 top-5 flex items-center gap-2">
        <span
          className={cn(
            'h-2.5 w-2.5 rounded-full shadow-[0_0_12px_rgba(96,165,250,0.45)]',
            accent.dotClassName
          )}
        />

        {modeLabel ? (
          <span className="rounded-full border border-blue-300/15 bg-[#101D3B]/80 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-blue-100">
            {modeLabel}
          </span>
        ) : null}
      </div>

      <div className="relative flex min-h-[224px] flex-col justify-between">
        {templateDecoration}

        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-300/15 bg-[#101D3B]/75 px-3 py-1 text-[11px] font-medium text-cyan-100">
            <Sparkles className="h-3.5 w-3.5" />
            {templateMeta.label}
          </div>

          <div className="mt-5 max-w-[18rem] text-2xl font-semibold tracking-[-0.02em] text-white">
            {title}
          </div>

          <div className="mt-3 max-w-[22rem] text-sm leading-6 text-slate-300">
            {subtitle || templateMeta.description}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-300">
          <div className="rounded-full border border-blue-300/15 bg-[#101D3B]/75 px-3 py-1.5">
            {templateMeta.label}
          </div>

          <div className="rounded-full border border-blue-300/15 bg-[#101D3B]/75 px-3 py-1.5">
            {backgroundMeta.label}
          </div>

          {meta ? (
            <div className="inline-flex items-center gap-2 rounded-full border border-blue-300/15 bg-[#101D3B]/75 px-3 py-1.5">
              <Clock3 className="h-3.5 w-3.5" />
              {meta}
            </div>
          ) : null}
        </div>
      </div>

      <div
        className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/30 to-transparent"
        aria-hidden
      />
    </div>
  )
}

export default ProjectDisplayPreviewCard