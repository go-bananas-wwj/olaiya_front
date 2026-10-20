export const FAMILY_COLORS = ['#637cdb','#af74cb','#39a5ac','#dd9970','#c26a91','#8e91cf','#79a3cc','#c6aa58']
export function familyAssignments(artifact, projection) {
  if (!artifact.source_index_sha256 || artifact.source_index_sha256 !== projection?.source_index_sha256) return new Map()
  return new Map(artifact.assignments.filter(([id, family])=>Number.isInteger(id)&&Number.isInteger(family)&&family>=0&&family<artifact.k))
}
