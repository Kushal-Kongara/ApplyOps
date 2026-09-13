interface Props {
  label: string
  value: number
  tone?: 'default' | 'accent' | 'warn'
}

export function StatCard({ label, value, tone = 'default' }: Props) {
  return (
    <div className={`stat-card stat-card--${tone}`}>
      <div className="stat-card__value">{value}</div>
      <div className="stat-card__label">{label}</div>
    </div>
  )
}
