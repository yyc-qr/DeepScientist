import * as React from 'react'
import { ArrowUpRight, BookOpen, Sparkles, X } from 'lucide-react'

import { QuestCopilotComposer } from '@/components/workspace/QuestCopilotComposer'
import { Button } from '@/components/ui/button'
import type { QuestMessageAttachmentDraft } from '@/lib/hooks/useQuestMessageAttachments'
import { cn } from '@/lib/utils'

type AutonomousSetupIntakeSurfaceProps = {
  locale: 'en' | 'zh'
  assistantLabel?: string | null
  value: string
  onValueChange: (value: string) => void
  attachments: QuestMessageAttachmentDraft[]
  onQueueFiles: (files: File[]) => void
  onRemoveAttachment: (draftId: string) => void
  onSubmit: () => Promise<void> | void
  submitting?: boolean
  error?: string | null
  onSwitchToForm: () => void
  onSwitchToCopilot: () => void
  onOpenBenchStore?: () => void
  onClose?: () => void
}

function copy(locale: 'en' | 'zh') {
  return locale === 'zh'
    ? {
        title: '你想研究什么？',
        body:
          '直接描述目标、已有材料、约束和期望产出；可以把论文、代码、数据或 reviewer comments 一起拖进来。SetupAgent 会先帮你整理计划，再判断更适合全自动还是协作模式。',
        placeholder:
          '可以这样写：\n我想基于这篇论文和已有代码复现 baseline，并继续优化方法。已有材料包括……\n运行限制：1 张 GPU，最多跑 24 小时；可以/不可以使用外部 API；数据需要保密。\n希望产出：可信 baseline、改进实验、分析图表，最终可能写成论文。',
        sendLabel: '交给 SetupAgent',
        stopLabel: '停止',
        enterHint: '拖入文件 · Enter 发送 · Shift+Enter 换行',
        assistantLabel: 'SetupAgent 只做启动规划，不会直接开始研究执行',
        manualAutonomous: '手动进入全自动',
        manualCopilot: '手动进入协作模式',
        benchText: '还不确定任务 → 点击“BenchStore”阅读开放任务',
        closeLabel: '关闭',
      }
    : {
        title: 'What do you want to research?',
        body:
          'Describe the goal, materials, constraints, and desired output. Drop in papers, code, data, or reviewer comments. SetupAgent will plan first, then recommend autonomous or Copilot mode.',
        placeholder:
          'You can write:\nI want to reproduce the baseline from this paper and existing repo, then keep optimizing the method. Available materials include…\nConstraints: 1 GPU, up to 24 hours; external APIs allowed/not allowed; data must stay private.\nDesired output: trusted baseline, improved experiments, analysis figures, and possibly a paper draft.',
        sendLabel: 'Send to SetupAgent',
        stopLabel: 'Stop',
        enterHint: 'Drop files · Enter to send · Shift+Enter for newline',
        assistantLabel: 'SetupAgent plans the launch only. It will not start research execution yet.',
        manualAutonomous: 'Manual autonomous',
        manualCopilot: 'Manual Copilot',
        benchText: 'Not sure yet → click “BenchStore” to browse open tasks',
        closeLabel: 'Close',
      }
}

export function AutonomousSetupIntakeSurface(
  props: AutonomousSetupIntakeSurfaceProps
) {
  const t = copy(props.locale)

  return (
    <div
      className="
        relative flex h-full min-h-0 flex-col overflow-hidden
        bg-[#071126]
        text-slate-100
      "
      data-onboarding-id="start-research-intake"
    >
      {/* 背景光效 */}
      <div
        className="pointer-events-none absolute inset-0 overflow-hidden"
        aria-hidden="true"
      >
        <div
          className="
            absolute left-[-12%] top-[-26%]
            h-[560px] w-[560px]
            rounded-full
            bg-blue-500/20
            blur-[110px]
          "
        />

        <div
          className="
            absolute right-[-10%] top-[-24%]
            h-[600px] w-[600px]
            rounded-full
            bg-violet-500/20
            blur-[120px]
          "
        />

        <div
          className="
            absolute bottom-[-32%] left-[25%]
            h-[640px] w-[640px]
            rounded-full
            bg-cyan-400/10
            blur-[130px]
          "
        />

        <div
          className="
            absolute inset-0
            bg-[linear-gradient(rgba(255,255,255,0.018)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.018)_1px,transparent_1px)]
            bg-[size:48px_48px]
          "
        />

        <div
          className="
            absolute inset-0
            bg-[radial-gradient(circle_at_50%_20%,rgba(67,97,238,0.10),transparent_46%)]
          "
        />
      </div>

      {/* 关闭按钮 */}
      <div className="absolute right-4 top-4 z-20">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="
            rounded-full
            border border-blue-200/10
            bg-[#101a34]/80
            text-slate-300
            backdrop-blur-xl
            hover:bg-[#172449]
            hover:text-white
          "
          onClick={props.onClose}
          aria-label={t.closeLabel}
          data-onboarding-id="start-research-close"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div
        className="
          feed-scrollbar modal-scrollbar
          relative z-10 min-h-0 flex-1
          overflow-y-auto
          px-4 py-5
          sm:px-8 sm:py-8
        "
      >
        <div
          className="
            mx-auto flex min-h-full w-full max-w-6xl
            flex-col justify-start gap-5
            pt-10
            sm:justify-center sm:gap-7 sm:pt-0
          "
        >
          {/* 标题区 */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div
                className="
                  inline-flex items-center gap-2
                  rounded-full
                  border border-cyan-300/20
                  bg-cyan-400/[0.06]
                  px-3 py-1
                  text-[11px] font-medium
                  uppercase tracking-[0.18em]
                  text-cyan-200
                  backdrop-blur-xl
                "
              >
                <Sparkles className="h-3.5 w-3.5" />
                Start Research
              </div>

              <h1
                className="
                  mt-4 max-w-3xl
                  text-[32px] font-semibold
                  leading-[1.04]
                  tracking-[-0.045em]
                  text-white
                  sm:text-6xl sm:leading-[0.98]
                "
              >
                {t.title}
              </h1>

              <p
                className="
                  mt-4 max-w-2xl
                  text-sm leading-7
                  text-slate-300
                  sm:text-[15px]
                "
              >
                {t.body}
              </p>

              <p className="mt-2 text-xs leading-5 text-slate-500">
                {props.assistantLabel || t.assistantLabel}
              </p>
            </div>

            {/* 模式按钮 */}
            <div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">
              <Button
                type="button"
                variant="outline"
                className="
                  w-full rounded-full
                  border-blue-300/20
                  bg-blue-400/[0.06]
                  text-blue-100
                  backdrop-blur-xl
                  hover:border-blue-300/35
                  hover:bg-blue-400/[0.12]
                  hover:text-white
                  sm:w-auto
                "
                onClick={props.onSwitchToCopilot}
              >
                <ArrowUpRight className="mr-1.5 h-4 w-4" />
                {t.manualCopilot}
              </Button>

              <Button
                type="button"
                className="
                  w-full rounded-full
                  border border-violet-300/15
                  bg-gradient-to-r
                  from-blue-500
                  via-indigo-500
                  to-violet-500
                  text-white
                  shadow-[0_14px_34px_-20px_rgba(99,102,241,0.95)]
                  hover:brightness-110
                  sm:w-auto
                "
                onClick={props.onSwitchToForm}
                data-onboarding-id="start-research-intake-form"
              >
                {t.manualAutonomous}
              </Button>
            </div>
          </div>

          {/* 主输入卡片 */}
          <div
            className={cn(
              `
              mx-auto w-full
              rounded-[26px]
              border border-blue-300/15
              bg-[#0d1830]/92
              p-3
              shadow-[0_40px_100px_-55px_rgba(59,130,246,0.75)]
              backdrop-blur-2xl
              sm:rounded-[38px]
              sm:p-5
              `,
              props.error &&
                'border-rose-400/35 shadow-[0_35px_90px_-50px_rgba(244,63,94,0.5)]'
            )}
          >
            <QuestCopilotComposer
              value={props.value}
              onValueChange={props.onValueChange}
              onSubmit={props.onSubmit}
              submitting={props.submitting}
              placeholder={t.placeholder}
              enterHint={t.enterHint}
              sendLabel={t.sendLabel}
              stopLabel={t.stopLabel}
              attachments={props.attachments}
              onQueueFiles={props.onQueueFiles}
              onRemoveAttachment={props.onRemoveAttachment}
              shellClassName="
                rounded-[22px]
                border border-blue-200/10
                bg-[#101a34]/95
                text-slate-100
                shadow-[0_22px_60px_-38px_rgba(59,130,246,0.65)]
                sm:rounded-[28px]
              "
              textareaClassName="
                min-h-[170px]
                px-4 pt-4 pb-16
                text-[14px] leading-7
                text-slate-100
                placeholder:text-slate-500
                sm:min-h-[320px]
                sm:px-5 sm:pt-5
                sm:text-[15px]
                lg:min-h-[360px]
              "
            />

            {props.error ? (
              <div className="px-1 pt-3 text-sm text-rose-300">
                {props.error}
              </div>
            ) : null}
          </div>

          {/* BenchStore */}
          <div
            className="
              mx-auto flex w-full max-w-3xl
              items-center justify-center
              text-center
              text-sm leading-6
              text-slate-400
            "
          >
            <button
              type="button"
              className="
                inline-flex max-w-full items-center gap-1.5
                rounded-full
                border border-blue-300/15
                bg-blue-400/[0.05]
                px-4 py-2
                text-slate-300
                backdrop-blur-xl
                transition
                hover:border-blue-300/30
                hover:bg-blue-400/[0.10]
                hover:text-white
              "
              onClick={props.onOpenBenchStore}
            >
              <BookOpen className="h-3.5 w-3.5 text-blue-300" />
              {t.benchText}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AutonomousSetupIntakeSurface