import photos from './productPhotos.json'

export function ProductPhoto({ product, side, mini = false }) {
  const photo = product && photos[String(product.id)]
  const matched = photo && product.source_url === photo.source_page
  return matched ? <img className={mini ? 'ss-photo-mini' : 'ss-photo'} src={photo.src} alt={`${product.brand} ${product.name}参考图`} loading={mini ? 'lazy' : 'eager'} />
    : <span className={mini ? 'ss-photo-label' : 'ss-photo-unavailable'}>{mini ? side : product ? '暂未收录产品参考图' : '正在读取产品…'}</span>
}

export function SectionHeading({ id, title, a, b, children }) {
  return <div className="ss-section-heading" id={id}>
    <ProductPhoto product={a} side="A" mini />
    <h2>{title}</h2>
    <ProductPhoto product={b} side="B" mini />
    {children}
  </div>
}

export const productPhotos = photos
