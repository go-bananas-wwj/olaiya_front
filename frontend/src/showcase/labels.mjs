export const DIRECTIONS = ['保湿', '抗皱', '修护', '舒缓', '抗氧化', '美白', '控油祛痘', '焕肤']
export const LEVELS = { human_rct: '人体随机对照研究', human_ct: '人体试验／消费者测试', human_open: '人体开放／观察研究', in_vitro: '体外研究（间接）', animal: '动物研究（间接）', oral: '口服研究', review: '综述（间接）', regulation: '法规资料', unknown: '未明确分级' }
export const TYPES = { paper: '论文', database: '功能分类（非功效实证）', regulation: '法规（非功效实证）', patent: '专利（未经同行评议）', supplier: '供应商（未经同行评议）', book: '工具书（行业参考，低强度）', white_paper: '白皮书（不计入主指数）' }
export const ingredientName = i => i.cn_name || i.inci_name
