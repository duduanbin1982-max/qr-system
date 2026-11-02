import { api } from '@/lib/api.js'


export async function loadAllMaterialOptions() {
  const materials = []
  const limit = 500
  for (let page = 1; ; page += 1) {
    const data = await api.domains.materials.listMaterials({ page, limit })
    const batch = data.materials || []
    materials.push(...batch)
    if (!batch.length || materials.length >= Number(data.total ?? materials.length)) break
  }
  return materials
}
