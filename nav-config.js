/* 左侧导航栏显示配置。
 *
 * 直接编辑本文件的 show 字段即可控制侧栏显示哪些入口：
 *   show: true  -> 显示；false -> 隐藏（页面本身仍可通过 URL 访问）。
 * 也可以在浏览器「资料更新」页的「导航显示设置」里勾选，选择会保存在
 * localStorage 的 nav.config 中，优先级高于本文件。
 *
 * 说明：近期新增的实验性页面默认全部关闭，保持侧栏聚焦核心 wiki / 一图流。
 */
window.WIKI_NAV_CONFIG = {
  show: {
    '#/': true,
    '#/dialogues': false,
    '#/mechanics': false,
    '#/maps': false,
    '#/ai': false,
    '#/code': false,
    '#/enhance': false,
    '#/search': true,
    '#/tools': true,
    '#/archive': true
  },
  labels: {
    '#/': '资料馆总览',
    '#/dialogues': '剧情对话',
    '#/mechanics': '机制规则',
    '#/maps': '战斗地图',
    '#/ai': '自动战斗 AI',
    '#/code': '客户端代码',
    '#/enhance': '强化与随机',
    '#/search': '全站搜索',
    '#/tools': '离线工具',
    '#/archive': '资料更新'
  },
  // Set true to show every entry regardless of the show flags.
  showAll: false
};
