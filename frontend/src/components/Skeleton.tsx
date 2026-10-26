// Скелетоны вместо «Загружаем…»: повторяют раскладку экрана, чтобы при загрузке ничего не прыгало.
import type { CSSProperties } from 'react'

export function Skel({ w, h = 12, r, style }: { w?: number | string; h?: number | string; r?: number; style?: CSSProperties }) {
  return <span className="skel" style={{ width: w, height: h, borderRadius: r, ...style }} />
}

function Busy({ label }: { label: string }) {
  return <span className="sr-only">{label}</span>
}

export function DoctorSkeleton() {
  return (
    <div className="doctor" aria-busy="true">
      <Busy label="Загружаем пациентов…" />
      <div className="roster">
        <div className="roster-top"><Skel w={140} h={18} /><Skel w="100%" h={38} r={8} /></div>
        <div className="roster-list">
          {Array.from({ length: 9 }, (_, i) => (
            <div key={i} className="skel-row">
              <Skel w={36} h={36} r={18} />
              <span className="skel-col"><Skel w={`${60 + ((i * 17) % 30)}%`} h={13} /><Skel w="45%" h={11} /></span>
              <Skel w={26} h={20} r={6} />
            </div>
          ))}
        </div>
      </div>
      <div className="card">
        <div className="head"><Skel w={52} h={52} r={26} /><span className="skel-col"><Skel w={220} h={22} /><Skel w={360} h={13} /></span></div>
        <div className="stats skel-stats">{[0, 1, 2, 3].map(i => <div key={i} className="stat"><Skel w="55%" h={11} /><Skel w="40%" h={26} /><Skel w="65%" h={11} /></div>)}</div>
        <Skel w={160} h={16} style={{ marginBottom: 12 }} />
        {[0, 1, 2].map(i => <div key={i} className="skel-panel" style={{ height: 112 }} />)}
      </div>
      <div className="rail">
        <Skel w={180} h={12} />
        <div className="skel-panel" style={{ height: 220 }} />
        <div className="skel-panel" style={{ height: 150 }} />
        <div className="skel-panel" style={{ height: 180 }} />
      </div>
    </div>
  )
}

export function AnalyticsSkeleton() {
  return (
    <div className="an-skel" aria-busy="true">
      <Busy label="Загружаем отчёт…" />
      <div className="an-kpis">
        <div className="stats skel-stats">{[0, 1, 2, 3].map(i => <div key={i} className="stat"><Skel w="50%" h={11} /><Skel w="35%" h={28} /><Skel w="70%" h={11} /></div>)}</div>
        <div className="skel-panel" style={{ height: 118, margin: 0 }} />
      </div>
      <div className="an-grid">
        <div className="an-col"><div className="skel-panel" style={{ height: 420 }} /><div className="skel-panel" style={{ height: 260 }} /></div>
        <div className="an-col"><div className="skel-panel" style={{ height: 300 }} /><div className="skel-panel" style={{ height: 220 }} /></div>
      </div>
    </div>
  )
}

export function PhoneSkeleton() {
  return (
    <div className="phone" aria-busy="true">
      <Busy label="Загружаем…" />
      <div className="phone-head"><Skel w={150} h={12} /><Skel w={230} h={24} style={{ marginTop: 8 }} /></div>
      <div className="phone-body">
        <div className="skel-panel" style={{ height: 150, borderRadius: 14 }} />
        <div className="skel-panel" style={{ height: 120, borderRadius: 14 }} />
        <div className="skel-panel" style={{ height: 160, borderRadius: 14 }} />
      </div>
    </div>
  )
}
