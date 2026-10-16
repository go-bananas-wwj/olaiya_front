// 单位价由后端严格按 ml / g 分开计算，来源缺失时不猜。
export default function PriceInfo({ product }) {
  const sourceIsUrl = /^https?:\/\//i.test(product.price_source || '')
  return (
    <div className="text-sm">
      <div className="font-semibold font-num text-pearl-ink tabular-nums">
        <span>{product.price_current == null ? '暂无价格' : `参考价 ¥${Number(product.price_current).toFixed(2)}`}</span>
        {product.spec && <span className="font-normal text-pearl-ink-2"> / {product.spec}</span>}
      </div>
      {product.unit_price != null && (
        <div className="text-xs text-pearl-ink-2 mt-1">¥{Number(product.unit_price).toFixed(2)} / {product.unit_price_unit}</div>
      )}
      {product.price_current != null && (
        <div className="text-xs text-pearl-ink-3 mt-1 break-words">
          {product.price_source ? (
            sourceIsUrl ? <a href={product.price_source} target="_blank" rel="noreferrer" className="text-iris hover:underline">价格来源 ↗</a>
              : <span>价格来源：{product.price_source}</span>
          ) : '价格来源未记录'}
          {product.price_recorded_at && <span> · 记录于 {product.price_recorded_at}</span>}
        </div>
      )}
    </div>
  )
}
