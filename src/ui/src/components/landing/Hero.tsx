'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { FolderOpen, Sparkles } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { CreateCopilotProjectDialog } from '@/components/projects/CreateCopilotProjectDialog'
import { CreateProjectDialog } from '@/components/projects/CreateProjectDialog'
import { OpenQuestDialog } from '@/components/projects/OpenQuestDialog'
import { BenchStoreDialog } from '@/components/landing/BenchStoreDialog'
import { Button } from '@/components/ui/button'
import { FadeContent, GlareHover } from '@/components/react-bits'
import { client } from '@/lib/api'
import { useMobileViewport } from '@/lib/hooks/useMobileViewport'
import { useI18n } from '@/lib/i18n'
import { filterProjectsVisibleQuests } from '@/lib/questVisibility'
import { useOnboardingStore } from '@/lib/stores/onboarding'
import { useUILanguageStore } from '@/lib/stores/ui-language'
import { runtimeVersion } from '@/lib/runtime/quest-runtime'
import { normalizeBuiltinRunnerName, runnerLabel } from '@/lib/runnerBranding'
import type { StartResearchTemplate } from '@/lib/startResearch'
import type { QuestMessageAttachmentDraft } from '@/lib/hooks/useQuestMessageAttachments'
import type { ConnectorAvailabilitySnapshot, QuestSummary } from '@/types'
import type { BenchEntry, BenchSetupPacket } from '@/lib/types/benchstore'
import { EntryCoachDialog } from './EntryCoachDialog'
import { UpdateReminderDialog } from './UpdateReminderDialog'


export type LandingDialogRequest = 'quests' | 'copilot' | 'autonomous' | 'benchstore'

type ActiveLandingDialog = LandingDialogRequest | null

function sortQuests(items: QuestSummary[]) {
  return [...items].sort((left, right) => {
    const leftAt = Date.parse(left.updated_at || '')
    const rightAt = Date.parse(right.updated_at || '')
    return rightAt - leftAt
  })
}

function buildBenchstoreContextFromEntry(entry: BenchEntry | null | undefined, setupAgentLabel: string) {
  if (!entry) return null
  return {
    entry_id: entry.id,
    entry_name: entry.name,
    one_line: entry.one_line ?? null,
    task_description: entry.task_description ?? null,
    paper: entry.paper ?? {},
    capability_tags: entry.capability_tags ?? [],
    track_fit: entry.track_fit ?? [],
    task_mode: entry.task_mode ?? null,
    requires_execution: entry.requires_execution ?? null,
    requires_paper: entry.requires_paper ?? null,
    resources: entry.resources ?? {},
    environment: entry.environment ?? {},
    image_path: entry.image_path ?? null,
    image_url: entry.image_url ?? null,
    recommended_when: entry.recommended_when ?? null,
    not_recommended_when: entry.not_recommended_when ?? null,
    download: entry.download ?? {},
    dataset_download: entry.dataset_download ?? {},
    credential_requirements: entry.credential_requirements ?? {},
    compatibility: entry.compatibility ?? {},
    benchmark_local_path: entry.install_state?.local_path ?? null,
    setup_agent_label: setupAgentLabel,
    catalog_source_file: entry.source_file ?? null,
    risk_flags: entry.risk_flags ?? [],
    risk_notes: entry.risk_notes ?? [],
    integrity_level: entry.integrity_level ?? null,
    snapshot_status: entry.snapshot_status ?? null,
    support_level: entry.support_level ?? null,
    primary_outputs: entry.primary_outputs ?? [],
    launch_profiles: entry.launch_profiles ?? [],
    version: entry.version ?? null,
    commercial: entry.commercial ?? {},
    display: entry.display ?? {},
  }
}

function buildBenchstoreSuggestedFormFromEntry(entry: BenchEntry | null | undefined, locale: 'en' | 'zh') {
  if (!entry) return null
  return {
    title: `${entry.name} Autonomous Research`,
    goal:
      entry.task_description ||
      entry.one_line ||
      (locale === 'zh'
        ? `先评估并整理 benchmark「${entry.name}」的启动方案。`
        : `Evaluate and prepare the launch plan for benchmark "${entry.name}".`),
    baseline_urls: entry.download?.url || '',
    paper_urls: entry.paper?.url || '',
    need_research_paper: entry.requires_paper ?? true,
    user_language: locale,
  }
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error || new Error('Failed to read file.'))
    reader.onload = () => {
      const result = String(reader.result || '')
      const base64 = result.includes(',') ? result.split(',', 2)[1] : result
      resolve(base64)
    }
    reader.readAsDataURL(file)
  })
}

async function uploadLocalAttachmentsToQuest(questId: string, attachments: QuestMessageAttachmentDraft[] = []) {
  const draftIds: string[] = []
  for (const attachment of attachments) {
    if (attachment.status !== 'success' || !attachment.file) continue
    const contentBase64 = await fileToBase64(attachment.file)
    const payload = await client.uploadChatAttachment(questId, {
      draft_id: attachment.draftId,
      file_name: attachment.name,
      mime_type: attachment.contentType || undefined,
      content_base64: contentBase64,
    })
    if (payload.ok && payload.draft_id) {
      draftIds.push(String(payload.draft_id))
    }
  }
  return draftIds
}

async function importSetupAttachmentsToQuest(
  questId: string,
  sourceQuestId?: string | null,
  attachments: Array<Record<string, unknown>> = []
) {
  const normalizedAttachments = attachments.filter((item) => {
    const questRelativePath = String(item.questRelativePath || item.quest_relative_path || '').trim()
    const path = String(item.path || '').trim()
    return Boolean(questRelativePath || path)
  })
  if (!sourceQuestId || normalizedAttachments.length === 0) return []
  const payload = await client.importQuestChatAttachments(questId, {
    source_quest_id: sourceQuestId,
    attachments: normalizedAttachments.map((item) => ({
      name: item.label || item.name || item.file_name,
      file_name: item.label || item.file_name || item.name,
      content_type: item.contentType || item.content_type || item.mime_type || null,
      quest_relative_path: item.questRelativePath || item.quest_relative_path || null,
      path: item.path || null,
    })),
  })
  if (!payload.ok) {
    throw new Error(payload.message || 'Failed to import launch attachments.')
  }
  return (payload.attachments || [])
    .map((item) => String(item.draft_id || '').trim())
    .filter(Boolean)
}

export default function Hero(props: {
  dialogRequest?: LandingDialogRequest | null
  onDialogRequestConsumed?: () => void
}) {
  const navigate = useNavigate()
  const { locale } = useI18n()
  const saveLanguagePreference = useUILanguageStore((state) => state.saveLanguagePreference)
  const {
    hydrated: onboardingHydrated,
    firstRunHandled,
    neverRemind,
    startTutorial,
    skipFirstRun,
    neverShowAgain,
  } = useOnboardingStore((state) => ({
    hydrated: state.hydrated,
    firstRunHandled: state.firstRunHandled,
    neverRemind: state.neverRemind,
    startTutorial: state.startTutorial,
    skipFirstRun: state.skipFirstRun,
    neverShowAgain: state.neverShowAgain,
  }))
  const heroRef = useRef<HTMLElement | null>(null)
  const isPortraitMode = useMobileViewport()
  const [globeRotation, setGlobeRotation] = useState(0)
  const globeRafRef = useRef<number | null>(null)
  const lastGlobeFrameRef = useRef<number | null>(null)
  const [activeDialog, setActiveDialog] = useState<ActiveLandingDialog>(null)

  useEffect(() => {
    let active = true
    void client.configDocument('config').then((payload) => {
      if (!active) return
      const structured = payload.meta?.structured_config && typeof payload.meta.structured_config === 'object'
        ? (payload.meta.structured_config as Record<string, unknown>)
        : {}
      setActiveRunnerName(normalizeBuiltinRunnerName(structured.default_runner))
    }).catch(() => {})
    return () => {
      active = false
    }
  }, [])
  const [connectorAvailability, setConnectorAvailability] = useState<ConnectorAvailabilitySnapshot | null>(null)
  const [connectorAvailabilityResolved, setConnectorAvailabilityResolved] = useState(false)
  const [entryCoachDismissed, setEntryCoachDismissed] = useState(false)
  const [quests, setQuests] = useState<QuestSummary[]>([])
  const [questsLoading, setQuestsLoading] = useState(false)
  const [questsError, setQuestsError] = useState<string | null>(null)
  const [deletingQuestId, setDeletingQuestId] = useState<string | null>(null)
  const [autonomousCreating, setAutonomousCreating] = useState(false)
  const [autonomousError, setAutonomousError] = useState<string | null>(null)
  const [benchSetupPacket, setBenchSetupPacket] = useState<BenchSetupPacket | null>(null)
  const [activeRunnerName, setActiveRunnerName] = useState(() => normalizeBuiltinRunnerName("codex"))
  const [setupQuestId, setSetupQuestId] = useState<string | null>(null)
  const [setupQuestCreating, setSetupQuestCreating] = useState(false)
  const [copilotSeed, setCopilotSeed] = useState<{
    title?: string
    message?: string
    setupQuestId?: string | null
    setupAttachments?: Array<Record<string, unknown>>
    localAttachments?: QuestMessageAttachmentDraft[]
  } | null>(null)
  const currentVersion = useMemo(() => runtimeVersion(), [])
  const landingModalOpen = activeDialog !== null

  useEffect(() => {
    document.body.classList.add('font-project')
    return () => document.body.classList.remove('font-project')
  }, [])

  useEffect(() => {
    if (!props.dialogRequest) {
      return
    }
    setActiveDialog(props.dialogRequest)
    props.onDialogRequestConsumed?.()
  }, [props.dialogRequest, props.onDialogRequestConsumed])

  useEffect(() => {
    if (!onboardingHydrated) {
      return
    }
    let active = true
    void client
      .connectorsAvailability()
      .then((payload) => {
        if (!active) return
        setConnectorAvailability(payload)
      })
      .catch(() => {
        if (!active) return
        setConnectorAvailability(null)
      })
      .finally(() => {
        if (active) {
          setConnectorAvailabilityResolved(true)
        }
      })
    return () => {
      active = false
    }
  }, [onboardingHydrated])

  const connectorCoachMode = useMemo(() => {
    if (!connectorAvailability?.should_recommend_binding) {
      return null
    }
    if (!connectorAvailability.has_enabled_external_connector) {
      return 'no_enabled' as const
    }
    const hasDeliveryTarget = connectorAvailability.available_connectors.some(
      (item) => item.enabled && item.has_delivery_target
    )
    if (!hasDeliveryTarget) {
      return 'no_target' as const
    }
    return 'recommended' as const
  }, [connectorAvailability])

  useEffect(() => {
    if (activeDialog !== 'quests') {
      return
    }
    let alive = true
    setQuestsLoading(true)
    void client
      .quests()
      .then((payload) => {
        if (!alive) return
        setQuests(sortQuests(filterProjectsVisibleQuests(payload)))
        setQuestsError(null)
      })
      .catch((caught) => {
        if (!alive) return
        setQuestsError(caught instanceof Error ? caught.message : 'Failed to load quests.')
      })
      .finally(() => {
        if (alive) {
          setQuestsLoading(false)
        }
      })
    return () => {
      alive = false
    }
  }, [activeDialog])

  useEffect(() => {
    if (activeDialog !== 'autonomous') {
      setAutonomousCreating(false)
      setAutonomousError(null)
    }
  }, [activeDialog])

  const cleanupSetupQuest = useCallback(async () => {
    if (!setupQuestId) return
    const questId = setupQuestId
    setSetupQuestId(null)
    try {
      await client.deleteQuest(questId)
    } catch {
      return
    }
  }, [setupQuestId])

  const openBenchStoreDialog = useCallback(() => {
    setBenchSetupPacket(null)
    if (setupQuestId) {
      void cleanupSetupQuest()
    }
    window.setTimeout(() => {
      setActiveDialog('benchstore')
    }, 120)
  }, [cleanupSetupQuest, setupQuestId])

  const ensureSetupQuest = useCallback(
    async (args: {
      message: string
      source: 'benchstore' | 'manual'
      form?: StartResearchTemplate | null
      setupPacket?: BenchSetupPacket | null
      entry?: BenchEntry | null
      attachments?: QuestMessageAttachmentDraft[]
      createOnly?: boolean
    }) => {
      const normalizedMessage = args.message.trim()
      const pendingAttachments = (args.attachments || []).filter(
        (item) => item.status === 'success' && item.file
      )
      if (!normalizedMessage && pendingAttachments.length === 0 && !args.createOnly) return null
      const suggestedForm =
        args.setupPacket?.suggested_form && typeof args.setupPacket.suggested_form === 'object'
          ? args.setupPacket.suggested_form
          : args.form
            ? { ...args.form }
            : args.source === 'benchstore'
              ? buildBenchstoreSuggestedFormFromEntry(args.entry, locale)
              : null
      const benchmarkContext =
        args.setupPacket?.launch_payload?.startup_contract &&
        typeof args.setupPacket.launch_payload.startup_contract === 'object' &&
        typeof args.setupPacket.launch_payload.startup_contract.benchstore_context === 'object'
          ? args.setupPacket.launch_payload.startup_contract.benchstore_context
          : args.source === 'benchstore'
            ? buildBenchstoreContextFromEntry(args.entry, 'Setup Agent')
: null

      const uploadAttachmentDrafts = async (questId: string) => {
        const uploadedDraftIds: string[] = []
        for (const attachment of pendingAttachments) {
          if (!attachment.file) continue
          const contentBase64 = await fileToBase64(attachment.file)
          const payload = await client.uploadChatAttachment(questId, {
            draft_id: attachment.draftId,
            file_name: attachment.name,
            mime_type: attachment.contentType || undefined,
            content_base64: contentBase64,
          })
          if (payload.ok) {
            uploadedDraftIds.push(attachment.draftId)
          }
        }
        return uploadedDraftIds
      }

      if (setupQuestId) {
        if (!args.createOnly) {
          const attachmentDraftIds = await uploadAttachmentDrafts(setupQuestId)
          await client.sendChat(
            setupQuestId,
            normalizedMessage,
            undefined,
            undefined,
            attachmentDraftIds
          )
        }
        return setupQuestId
      }

      setSetupQuestCreating(true)
      try {
        const titleBase =
          args.setupPacket?.project_title ||
          args.entry?.name ||
          args.form?.title ||
          (locale === 'zh' ? '启动协助' : 'Start setup')
        const nextIdPayload = await client.nextQuestId()
        const setupQuestIdValue = `B-${String(nextIdPayload?.quest_id || '').trim() || '001'}`
        const result = await client.createQuestWithOptions({
          goal: normalizedMessage,
          title: `SetupAgent · ${titleBase}`,
          quest_id: setupQuestIdValue,
          source: 'web-react',
          auto_start: !args.createOnly && pendingAttachments.length === 0 && Boolean(normalizedMessage),
          initial_message: !args.createOnly && pendingAttachments.length === 0 ? normalizedMessage : undefined,
          auto_bind_latest_connectors: false,
          startup_contract: {
            schema_version: 1,
            workspace_mode: 'copilot',
            launch_mode: 'custom',
            custom_profile: 'freeform',
            project_display: {
              template: 'blank',
              accent_color: 'mist',
              background_style: 'cloud',
            },
            start_setup_session: {
              source: args.source,
              locale,
              benchmark_context: benchmarkContext,
              suggested_form: suggestedForm,
            },
          },
        })
        setSetupQuestId(result.snapshot.quest_id)
        if (!args.createOnly && pendingAttachments.length > 0) {
          const attachmentDraftIds = await uploadAttachmentDrafts(result.snapshot.quest_id)
          if (attachmentDraftIds.length > 0) {
            await client.sendChat(
              result.snapshot.quest_id,
              normalizedMessage || (locale === 'zh' ? '请结合这些附件整理启动规划。' : 'Please prepare the launch plan from these attachments.'),
              undefined,
              undefined,
              attachmentDraftIds
            )
          }
        }
        return result.snapshot.quest_id
      } finally {
        setSetupQuestCreating(false)
      }
    },
    [locale, setupQuestId]
  )

  const shouldShowConnectorCoach = connectorAvailabilityResolved && connectorCoachMode !== null
  const shouldShowTutorialCoach = onboardingHydrated && !firstRunHandled && !neverRemind
  const entryCoachOpen =
    !entryCoachDismissed &&
    !landingModalOpen &&
    (shouldShowConnectorCoach || shouldShowTutorialCoach)

  useEffect(() => {
    const tick = (timestamp: number) => {
      const previous = lastGlobeFrameRef.current ?? timestamp
      const delta = Math.min(timestamp - previous, 48)
      lastGlobeFrameRef.current = timestamp

      if (!landingModalOpen && !entryCoachOpen) {
        setGlobeRotation((current) => current + delta * 0.018)
      }

      globeRafRef.current = requestAnimationFrame(tick)
    }

    globeRafRef.current = requestAnimationFrame(tick)

    return () => {
      if (globeRafRef.current !== null) {
        cancelAnimationFrame(globeRafRef.current)
      }
      globeRafRef.current = null
      lastGlobeFrameRef.current = null
    }
  }, [entryCoachOpen, landingModalOpen])

  useEffect(() => {
    const handleGlobeWheel = (event: WheelEvent) => {
      if (landingModalOpen || entryCoachOpen) return
      setGlobeRotation((current) => current + event.deltaY * 0.16)
    }

    window.addEventListener('wheel', handleGlobeWheel, { passive: true })
    return () => {
      window.removeEventListener('wheel', handleGlobeWheel)
    }
  }, [entryCoachOpen, landingModalOpen])


  useEffect(() => {
    const htmlStyle = document.documentElement.style
    const bodyStyle = document.body.style
    const previousHtmlOverflowY = htmlStyle.overflowY
    const previousHtmlOverflowX = htmlStyle.overflowX
    const previousBodyOverflow = bodyStyle.overflow
    const previousBodyOverflowX = bodyStyle.overflowX
    const previousBodyOverflowY = bodyStyle.overflowY

    const shouldLockBackground = landingModalOpen || entryCoachOpen
    htmlStyle.overflowX = 'hidden'
    htmlStyle.overflowY = shouldLockBackground ? 'hidden' : 'auto'
    bodyStyle.overflow = shouldLockBackground ? 'hidden' : 'auto'
    bodyStyle.overflowX = 'hidden'
    bodyStyle.overflowY = shouldLockBackground ? 'hidden' : 'auto'

    return () => {
      htmlStyle.overflowY = previousHtmlOverflowY
      htmlStyle.overflowX = previousHtmlOverflowX
      bodyStyle.overflow = previousBodyOverflow
      bodyStyle.overflowX = previousBodyOverflowX
      bodyStyle.overflowY = previousBodyOverflowY
    }
  }, [entryCoachOpen, landingModalOpen, isPortraitMode])

  return (
    <>
      <div
        className="relative min-h-[100svh] overflow-x-hidden text-white"
        style={{
          background:
            'radial-gradient(circle at 18% 18%, rgba(59,130,246,0.28), transparent 34%), radial-gradient(circle at 82% 16%, rgba(139,92,246,0.26), transparent 30%), radial-gradient(circle at 72% 84%, rgba(34,211,238,0.12), transparent 34%), linear-gradient(135deg, #050B18 0%, #0C1734 44%, #21124A 100%)',
        }}
      >
        {/* Global sci-tech background */}
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          <div
            className="absolute inset-0 opacity-[0.15]"
            style={{
              backgroundImage:
                'linear-gradient(rgba(255,255,255,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.08) 1px, transparent 1px)',
              backgroundSize: '42px 42px',
            }}
          />
          <div className="absolute -left-28 top-20 h-72 w-72 rounded-full bg-blue-500/20 blur-3xl" />
          <div className="absolute -right-24 top-10 h-80 w-80 rounded-full bg-violet-500/20 blur-3xl" />
          <div className="absolute bottom-[-120px] left-[38%] h-80 w-80 rounded-full bg-cyan-400/10 blur-3xl" />
        </div>

        {/* Completely redesigned top navigation */}
        <header className="relative z-40 border-b border-white/10 bg-[#07101f]/55 backdrop-blur-2xl">
          <div className="mx-auto flex h-[68px] w-full max-w-[94vw] items-center justify-between px-4 md:px-5">
          <button
  type="button"
  className="flex items-center gap-3 text-left"
  onClick={() => navigate('/')}
>
  <div className="h-10 w-10 overflow-hidden rounded-2xl border border-cyan-300/20 bg-white shadow-[0_0_30px_rgba(34,211,238,0.12)]">
    <img
      src={`${import.meta.env.BASE_URL}metis-research-logo.jpg`}
      alt="Metis Research"
      className="h-full w-full object-cover"
      draggable={false}
    />
  </div>

  <div>
    <div className="text-sm font-semibold tracking-[0.08em] text-white">
      Metis Research
    </div>

    <div className="text-[10px] uppercase tracking-[0.24em] text-blue-200/55">
      RESEARCH · MEMORY · EVALUATION
    </div>
  </div>
</button>
         <nav className="hidden items-center gap-2 md:flex">
  <button
    type="button"
    className="rounded-xl border border-white/10 bg-white/[0.06] px-4 py-2 text-sm text-slate-200 transition hover:bg-white/[0.12]"
    onClick={() => {
      void saveLanguagePreference(locale === 'zh' ? 'en' : 'zh-CN')
    }}
  >
    {locale === 'zh' ? 'English' : '中文'}
  </button>

  <button
    type="button"
    className="rounded-xl border border-white/10 bg-white/[0.06] px-4 py-2 text-sm text-slate-200 transition hover:bg-white/[0.12]"
    onClick={() => startTutorial(locale, '/', 'auto')}
  >
    {locale === 'zh' ? '教程' : 'Tutorial'}
  </button>

  <button
    type="button"
    className="rounded-xl border border-white/10 bg-white/[0.06] px-4 py-2 text-sm text-slate-200 transition hover:bg-white/[0.12]"
    onClick={() => navigate('/docs')}
  >
    {locale === 'zh' ? '文档' : 'Docs'}
  </button>

  <button
    type="button"
    className="rounded-xl border border-blue-300/20 bg-blue-400/10 px-4 py-2 text-sm text-blue-100 transition hover:bg-blue-400/20"
    onClick={openBenchStoreDialog}
  >
    BenchStore
  </button>

  <button
    type="button"
    className="rounded-xl border border-violet-300/20 bg-violet-400/10 px-4 py-2 text-sm text-violet-100 transition hover:bg-violet-400/20"
    onClick={() => navigate('/settings')}
  >
    {locale === 'zh' ? '设置' : 'Settings'}
  </button>
</nav>
          </div>
        </header>

        <section
          ref={heroRef}
          className="relative z-10"
        >
          <div className="mx-auto grid min-h-[calc(100svh-68px)] w-full max-w-[97vw] grid-cols-1 items-stretch gap-4 px-3 py-3 md:px-4 lg:grid-cols-[2fr_3fr] lg:gap-4 lg:py-4">
            {/* Left glass panel */}
            <FadeContent duration={0.6} y={18} blur={false} className="min-w-0">
              <div
                className="relative flex h-full min-h-[620px] flex-col overflow-hidden rounded-[24px] border border-white/15 bg-[#07111f]/58 p-6 shadow-[0_28px_80px_-32px_rgba(0,0,0,0.72)] backdrop-blur-2xl"
                data-onboarding-id="landing-hero"
              >
                <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/55 to-transparent" />
                <div className="pointer-events-none absolute -right-20 -top-24 h-52 w-52 rounded-full bg-blue-400/12 blur-3xl" />

                <div className="relative z-10 flex h-full flex-col">
                  <div>
                    <div className="inline-flex items-center gap-2 rounded-full border border-cyan-200/20 bg-cyan-200/[0.07] px-3.5 py-1.5 text-[11px] uppercase tracking-[0.18em] text-cyan-100">
                      <Sparkles className="h-3.5 w-3.5" />
                      {locale === 'zh' ? 'Metis Research · 记忆增强迭代科研平台' : 'Metis Research · ITERATIVE SCIENCE PLATFORM'}
                    </div>

                    <div className="mt-5 space-y-3">
                    <p className="text-[12px] uppercase tracking-[0.18em] text-cyan-200/75 md:text-[13px]">
                      QWEN · MEMORY · EVALUATION · TREE SEARCH
                    </p>
                   <h1 className="max-w-lg text-[24px] font-semibold leading-[1.15] tracking-tight text-white md:text-[30px]">
                      {locale === 'zh'
                        ?  '基于Qwen的记忆增强、证据评价与树搜索迭代科研平台'
                        : 'Memory-enhanced Evaluation and Tree-search for Iterative Science'}
                    </h1>
                    <p className="max-w-lg text-[13px] leading-6 text-slate-200/78">
                      {locale === 'zh'
                        ? '以科研记忆、证据评价与树搜索迭代为核心，融合文献检索、假设生成、多智能体审辩与实验规划，构建从科研问题到可验证科学假设的完整闭环。'
                        : 'Powered by Qwen, Metis Research combines scientific memory, evidence evaluation, iterative tree search, literature retrieval, hypothesis generation, multi-agent critique, and experiment planning into a verifiable research loop.'}
                    </p>
                    </div>
                  </div>

                  <div className="mt-5 flex flex-wrap gap-2">
                    {[
                      locale === 'zh' ? '文献检索' : 'Literature',
                      locale === 'zh' ? '科研记忆' : 'Memory',
                      locale === 'zh' ? '假设生成' : 'Hypothesis',
                      locale === 'zh' ? '多智能体审辩' : 'Multi-Agent',
                      locale === 'zh' ? '实验规划' : 'Experiment',
                    ].map((item) => (
                      <span
                        key={item}
                        className="rounded-full border border-white/10 bg-white/[0.055] px-2.5 py-1 text-[11px] text-slate-200"
                      >
                        {item}
                      </span>
                    ))}
                  </div>

                  <div
                    className="mt-5 grid grid-cols-2 gap-2.5"
                    data-onboarding-id="landing-entry-actions"
                  >
                    <GlareHover className="col-span-2 rounded-xl">
                      <Button
                        className="h-11 w-full rounded-xl border border-blue-200/20 bg-gradient-to-r from-blue-500 to-violet-500 px-6 text-white shadow-[0_14px_34px_-14px_rgba(81,108,255,0.9)] transition-all duration-200 hover:-translate-y-0.5 hover:brightness-110"
                        onClick={() => {
                          window.setTimeout(() => {
                            setActiveDialog('autonomous')
                          }, 120)
                        }}
                        data-onboarding-id="landing-start-research"
                      >
                        <Sparkles className="mr-2 h-4 w-4" />
                        {locale === 'zh' ? '启动科研任务' : 'Start Research'}
                      </Button>
                    </GlareHover>

                    <Button
                      variant="outline"
                      className="h-10 w-full rounded-xl border-white/15 bg-white/[0.07] px-4 text-white backdrop-blur-xl hover:bg-white/[0.13] hover:text-white"
                      onClick={() => setActiveDialog('quests')}
                    >
                      <FolderOpen className="mr-2 h-4 w-4" />
                      {locale === 'zh' ? '查看研究任务' : 'View Quests'}
                    </Button>

                    <Button
                      variant="outline"
                      className="h-10 w-full rounded-xl border-white/15 bg-white/[0.07] px-4 text-white backdrop-blur-xl hover:bg-white/[0.13] hover:text-white"
                      onClick={openBenchStoreDialog}
                      data-onboarding-id="landing-benchstore"
                    >
                      <Sparkles className="mr-2 h-4 w-4" />
                      BenchStore
                    </Button>
                  </div>

                  <div className="mt-6 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                    {[
                      ['01', locale === 'zh' ? '问题理解' : 'Problem'],
                      ['02', locale === 'zh' ? '知识整合' : 'Knowledge'],
                      ['03', locale === 'zh' ? '假设生成' : 'Hypothesis'],
                      ['04', locale === 'zh' ? '实验验证' : 'Experiment'],
                    ].map(([index, label]) => (
                      <div
                        key={index}
                        className="rounded-xl border border-white/10 bg-black/10 px-3 py-2"
                      >
                        <div className="text-[10px] tracking-[0.2em] text-blue-200/55">{index}</div>
                        <div className="mt-1 text-xs text-white md:text-sm">{label}</div>
                      </div>
                    ))}
                  </div>

                  <div className="mt-4 border-t border-white/10 pt-3 text-[11px] leading-5 text-slate-300/55">
                    <div>
                      {locale === 'zh'
                        ? 'Metis Research：记忆增强、证据评价与树搜索迭代科研平台。'
                        : 'Metis Research: Memory-enhanced Evaluation and Tree-search for Iterative Science, powered by Qwen.'}
                    </div>
                    {currentVersion ? <div className="mt-0.5">{`Metis Research v${currentVersion}`}</div> : null}
                  </div>
                </div>
              </div>
            </FadeContent>

            {/* Right: real Earth research HUD */}
            {!isPortraitMode ? (
              <div className="relative min-w-0">
                <div className="relative h-full min-h-[620px] overflow-hidden rounded-[24px] border border-white/10 bg-[#020711]/88 shadow-[0_28px_90px_-34px_rgba(0,0,0,0.85)]">
                  <div
                    className="absolute inset-0 opacity-25"
                    style={{
                      backgroundImage:
                        'linear-gradient(rgba(56,189,248,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(56,189,248,0.08) 1px, transparent 1px)',
                      backgroundSize: '54px 54px',
                    }}
                  />

                  <div className="absolute inset-0 bg-[radial-gradient(circle_at_68%_44%,rgba(37,99,235,0.18),transparent_30%),radial-gradient(circle_at_78%_58%,rgba(139,92,246,0.16),transparent_35%)]" />

                  <div className="absolute left-6 top-5 z-20">
                    <div className="text-[10px] uppercase tracking-[0.24em] text-blue-200/45">
                      Scientific Knowledge Network
                    </div>
                    <div className="mt-1 text-lg font-medium text-white">
                      {locale === 'zh' ? '智能科研知识网络' : 'Intelligent Research Network'}
                    </div>
                  </div>

                  <div className="absolute right-6 top-5 z-20 flex items-center gap-2 rounded-full border border-emerald-300/20 bg-emerald-400/10 px-3 py-1.5 text-[10px] text-emerald-200">
                    <span className="h-2 w-2 rounded-full bg-emerald-300 shadow-[0_0_12px_rgba(110,231,183,0.9)]" />
                    ONLINE
                  </div>

                  {/* outer orbital rings */}
                  <div
                    className="absolute left-[60%] top-[54%] h-[82%] w-[82%] -translate-x-1/2 -translate-y-1/2 rounded-full border border-blue-300/14 transition-transform duration-100"
                    style={{ transform: `translate(-50%, -50%) rotate(${globeRotation * 0.03}deg)` }}
                  />
                  <div
                    className="absolute left-[60%] top-[54%] h-[72%] w-[88%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border border-cyan-300/20 transition-transform duration-100"
                    style={{ transform: `translate(-50%, -50%) rotate(${18 + globeRotation * 0.05}deg)` }}
                  />
                  <div
                    className="absolute left-[60%] top-[54%] h-[60%] w-[94%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border border-violet-300/20 transition-transform duration-100"
                    style={{ transform: `translate(-50%, -50%) rotate(${-16 + globeRotation * 0.04}deg)` }}
                  />

                  {/* Real Earth */}
                  <div
                    className="absolute left-[60%] top-[55%] h-[64%] aspect-square -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-full border border-blue-200/40 shadow-[0_0_55px_rgba(37,99,235,0.48),0_0_100px_rgba(56,189,248,0.16)] transition-transform duration-100"
                    style={{
                      transform: `translate(-50%, -50%) rotate(${globeRotation * 0.18}deg)`,
                    }}
                  >
                    <img
                      src={`${import.meta.env.BASE_URL}earth.jpg`}
                      alt="Earth"
                      className="h-full w-full object-cover"
                      draggable={false}
                    />
                    <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_34%_28%,rgba(255,255,255,0.16),transparent_18%),linear-gradient(90deg,rgba(2,6,23,0.05),rgba(2,6,23,0.38))]" />
                  </div>

                  {/* connection streaks */}
                  <div className="absolute left-[25%] top-[39%] h-px w-[54%] rotate-[7deg] bg-gradient-to-r from-cyan-300/0 via-cyan-200/45 to-cyan-300/0" />
                  <div className="absolute left-[39%] top-[68%] h-px w-[42%] rotate-[-14deg] bg-gradient-to-r from-blue-300/0 via-blue-200/42 to-violet-300/0" />

                  {/* modules */}
                  <div className="absolute left-[13.2%] top-[38%] z-20 h-2.5 w-2.5 -translate-y-1/2 rounded-full bg-cyan-200 shadow-[0_0_18px_rgba(165,243,252,0.95)]" />
                  <div className="absolute left-[15%] top-[38%] z-20 -translate-y-1/2 rounded-2xl border border-cyan-300/30 bg-[#061324]/86 px-4 py-3 backdrop-blur-xl shadow-[0_0_28px_rgba(34,211,238,0.10)]">
                    <div className="text-[9px] tracking-[0.18em] text-cyan-200/55">MODULE 01</div>
                    <div className="mt-1 text-sm font-medium text-white">SEARCH</div>
                    <div className="mt-1 text-[11px] text-slate-300/60">{locale === 'zh' ? '文献检索与信息发现' : 'Literature discovery'}</div>
                  </div>

                  <div className="absolute right-[4%] top-[25%] z-20 rounded-2xl border border-violet-300/25 bg-[#1a0c31]/82 px-4 py-3 backdrop-blur-xl">
                    <div className="text-[9px] tracking-[0.18em] text-violet-200/55">MODULE 02</div>
                    <div className="mt-1 text-sm font-medium text-white">MEMORY</div>
                    <div className="mt-1 text-[11px] text-slate-300/60">{locale === 'zh' ? '科研记忆与知识沉淀' : 'Scientific memory'}</div>
                  </div>

                  <div className="absolute bottom-[11%] right-[7%] z-20 rounded-2xl border border-cyan-300/25 bg-[#062231]/82 px-4 py-3 backdrop-blur-xl">
                    <div className="text-[9px] tracking-[0.18em] text-cyan-200/55">MODULE 03</div>
                    <div className="mt-1 text-sm font-medium text-white">EVALUATION</div>
                    <div className="mt-1 text-[11px] text-slate-300/60">{locale === 'zh' ? '价值评价与智能审辩' : 'Value evaluation'}</div>
                  </div>

                  <div className="absolute bottom-5 left-1/2 -translate-x-1/2 text-center">
                    <div className="text-[9px] uppercase tracking-[0.16em] text-blue-200/45">
                      AUTO ROTATE · SCROLL TO EXPLORE
                    </div>
                    <div className="mt-1 text-[11px] text-slate-300/45">
                      {locale === 'zh' ? '地球自动旋转 · 滚动鼠标可加速' : 'Auto rotating Earth · scroll to accelerate'}
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </section>
      </div>

      <OpenQuestDialog
        open={activeDialog === 'quests'}
        quests={quests}
        loading={questsLoading}
        error={questsError}
        deletingQuestId={deletingQuestId}
        onClose={() => setActiveDialog(null)}
        onOpenQuest={(questId) => {
          setActiveDialog(null)
          navigate(`/projects/${questId}`)
        }}
        onDeleteQuest={async (questId) => {
          setDeletingQuestId(questId)
          try {
            await client.deleteQuest(questId)
            setQuests((current) => current.filter((item) => item.quest_id !== questId))
            setQuestsError(null)
          } catch (caught) {
            setQuestsError(caught instanceof Error ? caught.message : 'Failed to delete quest.')
          } finally {
            setDeletingQuestId(null)
          }
        }}
      />
      <BenchStoreDialog
        open={activeDialog === 'benchstore'}
        locale={locale}
        onClose={() => setActiveDialog(null)}
        setupQuestId={setupQuestId}
        setupQuestCreating={setupQuestCreating}
        onRequestSetupAgent={async ({ message, entry, setupPacket, attachments, createOnly }) => {
          await ensureSetupQuest({
            message,
            source: 'benchstore',
            entry: entry ?? null,
            setupPacket: setupPacket ?? benchSetupPacket,
            attachments,
            createOnly,
          })
        }}
        onStartWithSetupPacket={async (setupPacket) => {
          setBenchSetupPacket(setupPacket)
          setAutonomousError(null)
          if (setupQuestId) {
            void cleanupSetupQuest()
          }
          setActiveDialog('autonomous')
        }}
      />
      <CreateCopilotProjectDialog
        open={activeDialog === 'copilot'}
        onClose={() => {
          setCopilotSeed(null)
          setBenchSetupPacket(null)
          setActiveDialog(null)
          void cleanupSetupQuest()
        }}
        onBack={() => {
          setCopilotSeed(null)
          setBenchSetupPacket(null)
          setActiveDialog('autonomous')
          void cleanupSetupQuest()
        }}
        initialTitle={copilotSeed?.title || ''}
        initialMessage={copilotSeed?.message || ''}
        initialSetupQuestId={copilotSeed?.setupQuestId || null}
        initialSetupAttachments={copilotSeed?.setupAttachments || []}
        initialLocalAttachments={copilotSeed?.localAttachments || []}
        onCreated={(questId) => {
          setCopilotSeed(null)
          setActiveDialog(null)
          setBenchSetupPacket(null)
          void cleanupSetupQuest()
          navigate(`/projects/${questId}`)
        }}
      />
      <CreateProjectDialog
        open={activeDialog === 'autonomous'}
        onClose={() => {
          setBenchSetupPacket(null)
          setActiveDialog(null)
          void cleanupSetupQuest()
        }}
        onBack={() => {
          setBenchSetupPacket(null)
          setActiveDialog(null)
          void cleanupSetupQuest()
        }}
        loading={autonomousCreating}
        error={autonomousError}
        setupPacket={benchSetupPacket}
        setupQuestId={setupQuestId}
        setupQuestCreating={setupQuestCreating}
        onRequestSetupAgent={async ({ message, form, setupPacket, attachments, createOnly }) => {
          await ensureSetupQuest({
            message,
            source: setupPacket ? 'benchstore' : 'manual',
            form,
            setupPacket,
            attachments,
            createOnly,
          })
        }}
        onSwitchToCopilot={async ({ title, message, setupQuestId, setupAttachments, localAttachments }) => {
          setCopilotSeed({
            title,
            message,
            setupQuestId,
            setupAttachments: (setupAttachments || []).map((item) => ({ ...item })),
            localAttachments: [...(localAttachments || [])],
          })
          setActiveDialog('copilot')
        }}
        onOpenBenchStore={openBenchStoreDialog}
        onCreate={async (payload) => {
          if (!payload.goal.trim()) {
            return
          }
          setAutonomousCreating(true)
          setAutonomousError(null)
          try {
            const result = await client.createQuestWithOptions({
              goal: payload.goal.trim(),
              title: payload.title.trim() || undefined,
              quest_id: payload.quest_id?.trim() || undefined,
              source: 'web-react',
              auto_start: false,
              auto_bind_latest_connectors: false,
              requested_connector_bindings: payload.requested_connector_bindings,
              requested_baseline_ref: payload.requested_baseline_ref ?? undefined,
              startup_contract: payload.startup_contract ?? undefined,
            })
            const importedDraftIds = await importSetupAttachmentsToQuest(
              result.snapshot.quest_id,
              payload.launch_materials?.setup_quest_id || null,
              (payload.launch_materials?.setup_attachments || []).map((item) => ({ ...item }))
            )
            const localDraftIds = await uploadLocalAttachmentsToQuest(
              result.snapshot.quest_id,
              payload.launch_materials?.local_attachments || []
            )
            await client.sendChat(
              result.snapshot.quest_id,
              payload.goal.trim(),
              undefined,
              undefined,
              [...importedDraftIds, ...localDraftIds]
            )
            setActiveDialog(null)
            setBenchSetupPacket(null)
            setCopilotSeed(null)
            await cleanupSetupQuest()
            navigate(`/projects/${result.snapshot.quest_id}`)
          } catch (caught) {
            setAutonomousError(caught instanceof Error ? caught.message : 'Failed to create quest.')
          } finally {
            setAutonomousCreating(false)
          }
        }}
      />
      <UpdateReminderDialog />
      <EntryCoachDialog
        open={entryCoachOpen}
        locale={locale}
        connectorMode={connectorCoachMode || 'recommended'}
        showConnectorStep={shouldShowConnectorCoach}
        showTutorialStep={shouldShowTutorialCoach}
        onClose={() => setEntryCoachDismissed(true)}
        onSetLanguage={(language) => {
  void saveLanguagePreference(language === 'zh' ? 'zh-CN' : 'en')
}}
        onOpenConnectorSettings={() => {
          setEntryCoachDismissed(true)
          navigate('/settings/connector', { state: { configName: 'connectors' } })
        }}
        onStartTutorial={(language) => {
          setEntryCoachDismissed(true)
          startTutorial(language, '/', 'auto')
        }}
        onSkipTutorial={() => {
          skipFirstRun()
        }}
        onNeverShowTutorial={() => {
          neverShowAgain()
        }}
      />
    </>
  )
}
