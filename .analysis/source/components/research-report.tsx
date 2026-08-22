type Quality = { quality: { rows: number; gaps: number; duplicates: number; invalid_ohlc: number }; funding_rows: number; open_interest: { available: boolean; reason: string } }
type Report = {
  verdict: string
  reason: string
  experiment_id: string
  test_opened: boolean
  scope: { source: string; symbols: string[]; timeframe: string; years: number[] }
  selection: Record<string, { candidates_tested: number; eligible: number }>
  data_quality: Record<string, Quality>
  frozen_specification: { status: string; costs: { taker_fee_bps: number; half_spread_bps: number; slippage_bps: number }; selection_rule: string }
}

const number = new Intl.NumberFormat('ru-RU')

function StatusPill({ children }: { children: React.ReactNode }) {
  return <span className="inline-flex rounded-full border border-danger/40 bg-danger-soft px-3 py-1 font-mono text-xs font-semibold tracking-widest text-danger">{children}</span>
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className="border-t border-border py-4"><dt className="font-mono text-xs uppercase tracking-widest text-muted-foreground">{label}</dt><dd className="mt-2 text-2xl font-semibold tracking-tight text-foreground">{value}</dd><p className="mt-1 text-sm leading-6 text-muted-foreground">{note}</p></div>
}

export function ResearchReport({ report }: { report: Report }) {
  const symbols = Object.entries(report.selection)
  const tested = symbols.reduce((sum, [, item]) => sum + item.candidates_tested, 0)
  const rows = Object.values(report.data_quality).reduce((sum, item) => sum + item.quality.rows, 0)
  const funding = Object.values(report.data_quality).reduce((sum, item) => sum + item.funding_rows, 0)
  const costs = report.frozen_specification.costs
  const roundTrip = 2 * (costs.taker_fee_bps + costs.half_spread_bps + costs.slippage_bps)

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-5 py-6 md:px-10 md:py-10">
      <header className="flex flex-col gap-5 border-b border-border pb-6 md:flex-row md:items-end md:justify-between">
        <div className="flex flex-col gap-2"><p className="font-mono text-xs uppercase tracking-[0.22em] text-accent">Quant research / final report</p><h1 className="font-sans text-3xl font-semibold tracking-tight text-balance md:text-5xl">Edge не подтверждён</h1></div>
        <div className="flex flex-col items-start gap-2 md:items-end"><StatusPill>{report.verdict}</StatusPill><span className="font-mono text-xs text-muted-foreground">{report.experiment_id}</span></div>
      </header>

      <section className="grid gap-8 py-8 md:grid-cols-[1.25fr_0.75fr] md:py-12">
        <div className="flex flex-col gap-5"><p className="max-w-2xl text-lg leading-7 text-foreground">На TRAIN/VALIDATION ни одна гипотеза не прошла одновременно контроль множественных проверок, минимум сделок и положительную нижнюю границу доверительного интервала.</p><div className="border-l-2 border-accent pl-4"><p className="text-sm leading-6 text-muted-foreground">Это корректный отрицательный результат, а не ошибка прогона. Стратегия не была выбрана, поэтому закрытый TEST намеренно не вскрывался.</p></div></div>
        <dl className="grid grid-cols-2 gap-x-5"><Stat label="Гипотез" value={number.format(tested)} note="BTC + ETH"/><Stat label="Прошли" value="0" note="после BH-FDR"/><Stat label="Баров" value={number.format(rows)} note="реальных 1h"/><Stat label="TEST" value="Закрыт" note="не использован"/></dl>
      </section>

      <section className="border-y border-border py-8">
        <div className="mb-6 flex flex-col gap-2 md:flex-row md:items-end md:justify-between"><div><p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Данные и выборка</p><h2 className="mt-2 text-2xl font-semibold">Что именно проверялось</h2></div><p className="font-mono text-xs text-muted-foreground">{report.scope.years[0]}–{report.scope.years[1]} · {report.scope.timeframe} · {report.scope.source}</p></div>
        <div className="grid gap-px overflow-hidden rounded-lg border border-border bg-border md:grid-cols-2">{symbols.map(([symbol, result]) => { const quality = report.data_quality[symbol]; return <article key={symbol} className="bg-card p-5 md:p-6"><div className="flex items-center justify-between"><h3 className="font-mono text-lg font-semibold">{symbol}</h3><span className="font-mono text-xs text-accent">DATA OK</span></div><dl className="mt-6 grid grid-cols-2 gap-5 text-sm"><div><dt className="text-muted-foreground">Часовых баров</dt><dd className="mt-1 font-mono text-foreground">{number.format(quality.quality.rows)}</dd></div><div><dt className="text-muted-foreground">Funding records</dt><dd className="mt-1 font-mono text-foreground">{number.format(quality.funding_rows)}</dd></div><div><dt className="text-muted-foreground">Кандидатов</dt><dd className="mt-1 font-mono text-foreground">{number.format(result.candidates_tested)}</dd></div><div><dt className="text-muted-foreground">Gaps / invalid</dt><dd className="mt-1 font-mono text-foreground">{quality.quality.gaps} / {quality.quality.invalid_ohlc}</dd></div></dl></article>})}</div>
      </section>

      <section className="grid gap-8 py-8 md:grid-cols-2">
        <article><p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Защита от самообмана</p><h2 className="mt-2 text-xl font-semibold">Почему результат заслуживает доверия</h2><ul className="mt-5 flex list-disc flex-col gap-3 pl-5 text-sm leading-6 text-muted-foreground"><li>Сигнал исполняется только на open следующего бара.</li><li>Отбор выполнен только на хронологических TRAIN и VALIDATION.</li><li>Long и short, BTC-режимы, волатильность и горизонты проверялись отдельно.</li><li>Funding присоединён backward as-of; OI не имитировался и исключён.</li><li>Комиссия, half-spread и slippage дают {roundTrip.toFixed(0)} bps round trip.</li></ul></article>
        <article><p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Что означает вердикт</p><h2 className="mt-2 text-xl font-semibold">Не торговать эту спецификацию</h2><p className="mt-5 text-sm leading-6 text-muted-foreground">Нет статистического основания ожидать положительную доходность после издержек. Поскольку кандидат не прошёл validation, robustness, ablation и финальные TEST-метрики неприменимы: тестировать там нечего.</p><div className="mt-6 flex flex-wrap gap-5"><a className="inline-flex border-b border-accent pb-1 font-mono text-sm text-accent hover:text-foreground" href="/reports/latest.json">Открыть JSON →</a><a className="inline-flex border-b border-accent pb-1 font-mono text-sm text-accent hover:text-foreground" href="/reports/latest.html">Автономный HTML →</a></div></article>
      </section>

      <footer className="mt-auto flex flex-col gap-2 border-t border-border pt-5 text-xs leading-5 text-muted-foreground md:flex-row md:justify-between"><p>Research, not investment advice. No live trading is enabled.</p><p className="font-mono">Selection: {report.frozen_specification.status}</p></footer>
    </main>
  )
}
