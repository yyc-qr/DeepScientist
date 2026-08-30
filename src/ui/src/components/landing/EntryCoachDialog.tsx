import {
  ArrowRight,
  BookOpen,
  GraduationCap,
  Settings2,
  X,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Locale } from '@/types'

type ConnectorCoachMode = 'no_enabled' | 'no_target' | 'recommended'

const COPY = {
  en: {
    title: 'Before you start',
    subtitle:
      'Set up an external connector for milestone delivery, or jump into the guided demo first.',
    connector: {
      eyebrow: 'STEP 1',
      title: 'Bind a connector first',
      body: {
        no_enabled:
          'No external connector is enabled yet. It is recommended to configure one first so milestones, replies, and progress can reach you outside the web workspace.',
        no_target:
          'A connector is enabled, but there is no selectable delivery target yet. Open connector settings first, or send one message from the target connector and then come back here.',
        recommended:
          'It is recommended to confirm one default connector target before starting. Then Start Research and later project progress can be delivered to your normal external conversation.',
      },
      cta: {
        no_enabled: 'Open Connector Settings',
        no_target: 'Check Connector Settings',
        recommended: 'Bind Connector',
      },
      note:
        'This reminder appears on entry while no external connector is bound, so you can set delivery up before the first real run.',
    },
    tutorial: {
      eyebrow: 'STEP 2',
      title: 'Play the guided demo',
      body:
        'If you want a safe first pass through the interface, launch the guided demo. It walks through Start Research, Explorer, Canvas, Memory, and Copilot with a staged project.',
      zh: 'Chinese Demo',
      en: 'English Demo',
      skip: 'Skip demo for now',
      never: 'Do not remind again',
    },
    close: 'Close',
  },

  zh: {
    title: '开始之前',
    subtitle: '先配置一个外部连接器，或先播放一次引导演示。',
    connector: {
      eyebrow: '步骤 1',
      title: '先绑定一个连接器',
      body: {
        no_enabled:
          '你现在还没有启用任何外部连接器。建议先配置一个，这样研究过程中的里程碑、回复和进展可以直接发送到网页之外。',
        no_target:
          '你已经启用了连接器，但还没有可选择的投递目标。建议先进入连接器设置页检查配置，或者先在对应连接器中发一条消息，再回来继续。',
        recommended:
          '建议先确认一个默认连接器目标。这样之后“开始研究”和项目运行中的进展都可以直接同步出去。',
      },
      cta: {
        no_enabled: '前往连接器设置',
        no_target: '检查连接器设置',
        recommended: '绑定连接器',
      },
      note:
        '只要还没有绑定外部连接器，这个提醒在进入首页时就会继续出现，方便你在第一次真实运行前先完成投递配置。',
    },
    tutorial: {
      eyebrow: '步骤 2',
      title: '播放首次 Demo',
      body:
        '如果你想先安全地熟悉界面和工作流，可以先进入教程演示。它会一步步带你理解“开始研究”、Explorer、Canvas、Memory 和 Copilot。',
      zh: '中文演示',
      en: '英文演示',
      skip: '暂时跳过演示',
      never: '不再提醒',
    },
    close: '关闭',
  },
} as const

function stepLabel(
  label: string,
  fallback: string,
  showBoth: boolean,
) {
  if (showBoth) return label
  return fallback
}

export function EntryCoachDialog({
  open,
  locale,
  connectorMode,
  showConnectorStep,
  showTutorialStep,
  onClose,
  onOpenConnectorSettings,
  onSetLanguage,
  onStartTutorial,
  onSkipTutorial,
  onNeverShowTutorial,
}: {
  open: boolean
  locale: Locale
  connectorMode: ConnectorCoachMode
  showConnectorStep: boolean
  showTutorialStep: boolean
  onClose: () => void
  onOpenConnectorSettings: () => void
  onSetLanguage: (language: Locale) => void
  onStartTutorial: (language: 'zh' | 'en') => void
  onSkipTutorial: () => void
  onNeverShowTutorial: () => void
}) {
  if (!open) {
    return null
  }

  const t = COPY[locale]
  const showBoth = showConnectorStep && showTutorialStep

  return (
    <div
      className="
        pointer-events-none
        fixed inset-0 z-[10010]
        flex items-center justify-center
        bg-[#020817]/75
        p-4
        backdrop-blur-xl
      "
    >
      {/* ================================
          主弹窗
      ================================= */}
      <div
        className="
          pointer-events-auto
          relative
          flex
          max-h-[calc(100dvh-1.5rem)]
          w-full
          max-w-[980px]
          flex-col
          overflow-hidden
          rounded-[28px]
          border border-cyan-300/20
          bg-[linear-gradient(145deg,rgba(8,19,43,0.98),rgba(15,24,58,0.98)_52%,rgba(31,20,68,0.98))]
          text-white
          shadow-[0_0_0_1px_rgba(96,165,250,0.06),0_35px_120px_-35px_rgba(37,99,235,0.55)]
        "
      >
        {/* 蓝紫光效 */}
        <div
          className="
            pointer-events-none
            absolute -right-32 -top-40
            h-[420px] w-[420px]
            rounded-full
            bg-violet-600/20
            blur-[100px]
          "
        />

        <div
          className="
            pointer-events-none
            absolute -bottom-40 -left-32
            h-[420px] w-[420px]
            rounded-full
            bg-cyan-500/10
            blur-[100px]
          "
        />

        {/* ================================
            顶部标题
        ================================= */}
        <div
          className="
            relative
            flex items-start justify-between
            gap-4
            border-b border-blue-200/10
            bg-[#081326]/55
            px-6 py-5
          "
        >
          <div className="min-w-0">
            <div
              className="
                text-[11px]
                font-semibold
                uppercase
                tracking-[0.18em]
                text-cyan-300/80
              "
            >
              {locale === 'zh' ? '智能科研引导' : 'RESEARCH GUIDE'}
            </div>

            <h2
              className="
                mt-2
                text-2xl
                font-semibold
                tracking-tight
                text-white
              "
            >
              {t.title}
            </h2>

            <div
              className="
                mt-2
                max-w-2xl
                text-sm
                text-slate-300
              "
            >
              <div className="leading-7">
                {t.subtitle}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* 语言切换 */}
            <div
              className="
                inline-flex
                rounded-full
                border border-blue-200/15
                bg-white/[0.05]
                p-1
                backdrop-blur-xl
              "
            >
              <button
                type="button"
                onClick={() => onSetLanguage?.('zh')}
                className={cn(
                  'rounded-full px-3 py-1.5 text-xs font-semibold transition-all duration-200',
                  locale === 'zh'
                    ? 'bg-gradient-to-r from-blue-500 to-violet-500 text-white shadow-lg shadow-blue-500/20'
                    : 'text-slate-400 hover:bg-white/10 hover:text-white',
                )}
              >
                中文
              </button>

              <button
                type="button"
                onClick={() => onSetLanguage?.('en')}
                className={cn(
                  'rounded-full px-3 py-1.5 text-xs font-semibold transition-all duration-200',
                  locale === 'en'
                    ? 'bg-gradient-to-r from-blue-500 to-violet-500 text-white shadow-lg shadow-blue-500/20'
                    : 'text-slate-400 hover:bg-white/10 hover:text-white',
                )}
              >
                English
              </button>
            </div>

            {/* 关闭 */}
            <button
              type="button"
              onClick={onClose}
              className="
                inline-flex
                h-10 w-10
                items-center justify-center
                rounded-full
                text-slate-400
                transition
                hover:bg-white/10
                hover:text-white
              "
              aria-label={t.close}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* ================================
            内容
        ================================= */}
        <div
          className="
            feed-scrollbar
            modal-scrollbar
            relative
            min-h-0
            flex-1
            overflow-y-auto
            overscroll-contain
          "
        >
          <div
            className={cn(
              'grid gap-0',
              showBoth
                ? 'lg:grid-cols-[1.05fr_0.95fr]'
                : 'grid-cols-1',
            )}
          >
            {/* ============================
                连接器
            ============================= */}
            {showConnectorStep ? (
              <section
                className="
                  relative
                  overflow-hidden
                  border-r border-blue-200/10
                  bg-[#07152c]/60
                  px-6 py-6
                  text-white
                  lg:px-7 lg:py-7
                "
              >
                <div
                  className="
                    absolute inset-0
                    bg-[radial-gradient(circle_at_top_left,rgba(59,130,246,0.20),transparent_50%),radial-gradient(circle_at_bottom_right,rgba(139,92,246,0.14),transparent_45%)]
                  "
                />

                <div className="relative">
                  <div
                    className="
                      inline-flex
                      items-center gap-2
                      rounded-full
                      border border-cyan-300/20
                      bg-cyan-300/[0.06]
                      px-3 py-1
                      text-[11px]
                      font-semibold
                      uppercase
                      tracking-[0.16em]
                      text-cyan-200
                    "
                  >
                    <Settings2 className="h-3.5 w-3.5" />

                    {stepLabel(
                      t.connector.eyebrow,
                      locale === 'zh' ? '步骤 1' : 'STEP 1',
                      showBoth,
                    )}
                  </div>

                  <h3
                    className="
                      mt-4
                      text-2xl
                      font-semibold
                      tracking-tight
                      text-white
                    "
                  >
                    {t.connector.title}
                  </h3>

                  <div className="mt-3 text-sm text-slate-300">
                    <div className="leading-7">
                      {t.connector.body[connectorMode]}
                    </div>
                  </div>

                  <Button
                    type="button"
                    onClick={onOpenConnectorSettings}
                    className="
                      mt-6
                      h-12
                      rounded-full
                      border-0
                      bg-gradient-to-r
                      from-blue-500
                      via-indigo-500
                      to-violet-500
                      px-6
                      text-sm
                      font-semibold
                      text-white
                      shadow-[0_14px_35px_-12px_rgba(99,102,241,0.75)]
                      transition
                      hover:brightness-110
                    "
                  >
                    {t.connector.cta[connectorMode]}

                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>

                  <div className="mt-4 text-[12px] text-slate-400">
                    <div className="leading-6">
                      {t.connector.note}
                    </div>
                  </div>
                </div>
              </section>
            ) : null}

            {/* ============================
                教程
            ============================= */}
            {showTutorialStep ? (
              <section
                className="
                  relative
                  bg-[#0b1430]/45
                  px-6 py-6
                  lg:px-7 lg:py-7
                "
              >
                <div
                  className="
                    inline-flex
                    items-center gap-2
                    rounded-full
                    border border-violet-300/20
                    bg-violet-400/[0.07]
                    px-3 py-1
                    text-[11px]
                    font-semibold
                    uppercase
                    tracking-[0.16em]
                    text-violet-200
                  "
                >
                  <GraduationCap className="h-3.5 w-3.5" />

                  {stepLabel(
                    t.tutorial.eyebrow,
                    locale === 'zh' ? '步骤 1' : 'STEP 1',
                    showBoth,
                  )}
                </div>

                <h3
                  className="
                    mt-4
                    text-2xl
                    font-semibold
                    tracking-tight
                    text-white
                  "
                >
                  {t.tutorial.title}
                </h3>

                <div className="mt-3 text-sm text-slate-300">
                  <div className="leading-7">
                    {t.tutorial.body}
                  </div>
                </div>

                {/* Demo 卡片 */}
                <div className="mt-6 grid gap-3 sm:grid-cols-2">
                  <button
                    type="button"
                    onClick={() => onStartTutorial('zh')}
                    className="
                      group
                      rounded-[20px]
                      border border-blue-300/15
                      bg-white/[0.045]
                      px-4 py-4
                      text-left
                      backdrop-blur-xl
                      transition-all
                      duration-200
                      hover:-translate-y-0.5
                      hover:border-cyan-300/35
                      hover:bg-blue-400/[0.08]
                      hover:shadow-[0_15px_40px_-20px_rgba(59,130,246,0.6)]
                    "
                  >
                    <div
                      className="
                        flex items-center gap-2
                        text-sm font-semibold
                        text-white
                      "
                    >
                      <BookOpen className="h-4 w-4 text-cyan-300" />

                      {t.tutorial.zh}
                    </div>

                    <div
                      className="
                        mt-1
                        text-[12px]
                        leading-6
                        text-slate-400
                      "
                    >
                      {locale === 'zh'
                        ? '一步步熟悉首页、开始研究和项目工作区。'
                        : 'Walk through the landing page, Start Research, and workspace basics.'}
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={() => onStartTutorial('en')}
                    className="
                      group
                      rounded-[20px]
                      border border-violet-300/15
                      bg-white/[0.045]
                      px-4 py-4
                      text-left
                      backdrop-blur-xl
                      transition-all
                      duration-200
                      hover:-translate-y-0.5
                      hover:border-violet-300/35
                      hover:bg-violet-400/[0.08]
                      hover:shadow-[0_15px_40px_-20px_rgba(139,92,246,0.6)]
                    "
                  >
                    <div
                      className="
                        flex items-center gap-2
                        text-sm font-semibold
                        text-white
                      "
                    >
                      <GraduationCap className="h-4 w-4 text-violet-300" />

                      {t.tutorial.en}
                    </div>

                    <div
                      className="
                        mt-1
                        text-[12px]
                        leading-6
                        text-slate-400
                      "
                    >
                      {locale === 'zh'
                        ? '使用英文引导完成同一套首次演示。'
                        : 'Use the same guided flow in English.'}
                    </div>
                  </button>
                </div>

                {/* 底部按钮 */}
                <div
                  className="
                    mt-5
                    flex
                    flex-col
                    gap-2
                    sm:flex-row
                    sm:justify-end
                  "
                >
                  <Button
                    variant="ghost"
                    onClick={onSkipTutorial}
                    className="
                      rounded-full
                      text-slate-300
                      hover:bg-white/10
                      hover:text-white
                    "
                  >
                    {t.tutorial.skip}
                  </Button>

                  <Button
                    variant="secondary"
                    onClick={onNeverShowTutorial}
                    className="
                      rounded-full
                      border
                      border-blue-300/15
                      bg-white/[0.07]
                      text-white
                      hover:bg-white/[0.13]
                    "
                  >
                    {t.tutorial.never}
                  </Button>
                </div>
              </section>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}

export default EntryCoachDialog
