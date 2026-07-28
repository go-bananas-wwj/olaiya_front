// Cartoon rounded glass evidence card for a clicked ingredient orb.
export default function IngredientCard({ ing, onClose }) {
  if (!ing) return null
  return (
    <aside className="ing-card" key={ing.id}>
      <header className="ing-card-head">
        <span className="ing-dot" style={{ background: ing.color }} />
        <h3>{ing.name}</h3>
        <button className="ing-close" onClick={onClose} aria-label="关闭">
          ×
        </button>
      </header>

      <div className="ing-meta">
        INCI&nbsp;{ing.inci}&nbsp;&nbsp;·&nbsp;&nbsp;CAS&nbsp;{ing.cas}
      </div>

      <div className="ing-row">
        <label>功效</label>
        <div className="ing-chips">
          {ing.effects.map((e) => (
            <span className="ing-chip" key={e}>
              {e}
            </span>
          ))}
        </div>
      </div>

      <div className="ing-row">
        <label>文献起效浓度</label>
        <span className="ing-val">{ing.dose}</span>
      </div>

      <div className="ing-row">
        <label>证据</label>
        <span className="ing-val ing-ev">
          {ing.evidence.journal}
          {ing.evidence.pmid && (
            <>
              {' · '}
              <a
                href={`https://pubmed.ncbi.nlm.nih.gov/${ing.evidence.pmid}/`}
                target="_blank"
                rel="noreferrer"
              >
                PMID&nbsp;{ing.evidence.pmid}
              </a>
            </>
          )}
        </span>
      </div>

      <div className={`ing-badge ing-badge-${ing.badge.level}`}>{ing.badge.text}</div>
    </aside>
  )
}
