
        // ==================== 从模块获取数据 ====================
        
        // 解析注入的JSON数据
        const CHARACTER_DB = JSON.parse(document.querySelector('#widget-params [data-key="character_db"]').textContent || '{}');
        const LEGEND_NAMES = JSON.parse(document.querySelector('#widget-params [data-key="legend_names"]').textContent || '[]');
        const EPIC_NAMES = JSON.parse(document.querySelector('#widget-params [data-key="epic_names"]').textContent || '[]');
        const ELITE_NAMES = JSON.parse(document.querySelector('#widget-params [data-key="elite_names"]').textContent || '[]');
        const COMMON_NAMES = JSON.parse(document.querySelector('#widget-params [data-key="common_names"]').textContent || '[]');
        
        // 构建 ALL_LEGEND_CHARACTERS 数组
        const ALL_LEGEND_CHARACTERS = LEGEND_NAMES.map(name => ({
            name: name,
            type: CHARACTER_DB.legend[name]?.type || '未知'
        }));
        
        // 辅助函数
        function getCharacterInfo(name, rarity) {
            const db = CHARACTER_DB[rarity];
            if (db && db[name]) {
                return db[name];
            }
            return { type: '未知', pixelUrl: '' };
        }

        function getCharacterType(charName) {
            const char = ALL_LEGEND_CHARACTERS.find(c => c.name === charName);
            return char ? char.type : '未知';
        }

        // ==================== 原有配置代码（保持不变）====================

        function getWidgetParam(key, defaultValue) {
            const paramEl = document.querySelector(`#widget-params [data-key="${key}"]`);
            if (paramEl) {
                const value = paramEl.textContent.trim();
                if (value && !value.includes('{$') && value !== '') {
                    return value;
                }
            }
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.has(key)) {
                return decodeURIComponent(urlParams.get(key));
            }
            return defaultValue;
        }

        function getImageUrl(imgValue) {
            if (!imgValue) return '';
            if (imgValue.startsWith('http')) return imgValue;
            if (imgValue.startsWith('//')) return imgValue;
            if (imgValue.startsWith('/')) return imgValue;
            return imgValue;
        }

        function getAvatarUrl(charName, customUrl) {
            if (customUrl && (customUrl.startsWith('http') || customUrl.startsWith('//'))) {
                return customUrl;
            }
            return `头像${charName}.png`;
        }

        // 配置对象
        const WIDGET_CONFIG = {
            chuyu: {
                name: getWidgetParam('chuyu_name', '露西亚之血永存'),
                char: getWidgetParam('chuyu_char', '罗格妮达'),
                img: getWidgetParam('chuyu_img', ''),
                avatar: getWidgetParam('chuyu_avatar', '')
            },
            chongfeng: {
                name: getWidgetParam('chongfeng_name', '重逢之时'),
                chara: getWidgetParam('chongfeng_chara', '帕米娜'),
                charb: getWidgetParam('chongfeng_charb', '卡丽丝'),
                img: getWidgetParam('chongfeng_img', ''),
                avatara: getWidgetParam('chongfeng_avatara', ''),
                avatarb: getWidgetParam('chongfeng_avatarb', '')
            }
        };

        // 卡池配置
        const CHUYU_CONFIG = {
            poolName: WIDGET_CONFIG.chuyu.name,
            upCharacter: {
                name: WIDGET_CONFIG.chuyu.char,
                type: getCharacterType(WIDGET_CONFIG.chuyu.char),
                avatar: WIDGET_CONFIG.chuyu.avatar
            },
            img: WIDGET_CONFIG.chuyu.img
        };

        const CHONGFENG_CONFIG = {
            poolName: WIDGET_CONFIG.chongfeng.name,
            upCharacters: [
                { 
                    name: WIDGET_CONFIG.chongfeng.chara, 
                    type: getCharacterType(WIDGET_CONFIG.chongfeng.chara),
                    avatar: WIDGET_CONFIG.chongfeng.avatara
                },
                { 
                    name: WIDGET_CONFIG.chongfeng.charb, 
                    type: getCharacterType(WIDGET_CONFIG.chongfeng.charb),
                    avatar: WIDGET_CONFIG.chongfeng.avatarb
                }
            ],
            img: WIDGET_CONFIG.chongfeng.img
        };

        function buildCharactersDB() {
            const upNames = new Set([CHUYU_CONFIG.upCharacter.name, ...CHONGFENG_CONFIG.upCharacters.map(c => c.name)]);
            const legendList = [];
            
            legendList.push({ ...CHUYU_CONFIG.upCharacter, isUp: true, pool: 'chuyu' });
            CHONGFENG_CONFIG.upCharacters.forEach(char => legendList.push({ ...char, isUp: true, pool: 'chongfeng' }));
            
            ALL_LEGEND_CHARACTERS.forEach(char => {
                if (!upNames.has(char.name)) legendList.push({ name: char.name, type: char.type, isUp: false });
            });
            
            return { legend: legendList, epic: EPIC_NAMES, elite: ELITE_NAMES, common: COMMON_NAMES };
        }

        let characters = buildCharactersDB();

        function buildPoolConfig() {
            return {
                chuyu: {
                    name: CHUYU_CONFIG.poolName,
                    type: "初遇",
                    upCharacters: [CHUYU_CONFIG.upCharacter],
                    upRate: 0.5,
                    specialPity: 180,
                    specialPityText: "180抽内必得UP角色",
                    img: CHUYU_CONFIG.img
                },
                chongfeng: {
                    name: CHONGFENG_CONFIG.poolName,
                    type: "重逢",
                    upCharacters: CHONGFENG_CONFIG.upCharacters,
                    upRate: 0.75,
                    specialPity: 180,
                    specialPityText: "180抽内必得未拥有UP角色",
                    img: CHONGFENG_CONFIG.img
                }
            };
        }

        let pools = buildPoolConfig();

        let currentPool = 'chuyu';
        let globalPity = 0;
        let specialPity = { chuyu: 0, chongfeng: 0 };
        let ownedCharacters = new Set();
        let stats = { total: 0, legend: 0, epic: 0, elite: 0, common: 0, history: [], legendStats: {} };

        function init() { 
            const chuyuImgContainer = document.getElementById('chuyu-image-container');
            const chuyuImgUrl = getImageUrl(pools.chuyu.img);
            if (chuyuImgUrl) {
                chuyuImgContainer.innerHTML = `<img src="${chuyuImgUrl}" alt="初遇卡池" onerror="this.style.display='none'; this.parentElement.innerHTML='<div class=\'placeholder-text\'>初遇卡池</div>';">`;
            } else {
                chuyuImgContainer.innerHTML = '<div class="placeholder-text">初遇卡池</div>';
            }
            
            const chongfengImgContainer = document.getElementById('chongfeng-image-container');
            const chongfengImgUrl = getImageUrl(pools.chongfeng.img);
            if (chongfengImgUrl) {
                chongfengImgContainer.innerHTML = `<img src="${chongfengImgUrl}" alt="重逢卡池" onerror="this.style.display='none'; this.parentElement.innerHTML='<div class=\'placeholder-text\'>重逢卡池</div>';">`;
            } else {
                chongfengImgContainer.innerHTML = '<div class="placeholder-text">重逢卡池</div>';
            }
            
            updateUI(); 
        }

        function switchPool(pool) {
            currentPool = pool;
            document.querySelectorAll('.pool-card').forEach(card => card.classList.remove('active'));
            document.getElementById(`pool-card-${pool}`).classList.add('active');
            updateUI();
        }

        function resetStats() {
            if (!confirm('确定要重置所有统计数据吗？')) return;
            globalPity = 0;
            specialPity = { chuyu: 0, chongfeng: 0 };
            ownedCharacters.clear();
            stats = { total: 0, legend: 0, epic: 0, elite: 0, common: 0, history: [], legendStats: {} };
            updateUI();
            updateStats();
            document.getElementById('result-area').classList.add('hidden');
            alert('统计已重置！');
        }

        function updateUI() {
            const pool = pools[currentPool];
            document.getElementById('pool-name').textContent = pool.name;
            document.getElementById('pool-type').textContent = `邂逅类型：${pool.type}`;
            
            const upContainer = document.getElementById('up-characters');
            upContainer.innerHTML = pool.upCharacters.map(char => {
                const avatarUrl = getAvatarUrl(char.name, char.avatar);
                return `
                <div class="flex items-center bg-amber-50 px-4 py-2 rounded-lg border border-amber-200">
                    <img src="${avatarUrl}" alt="${char.name}" class="up-character-avatar mr-3" 
                         onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                    <div class="up-character-avatar-fallback mr-3" style="display:none;">${char.name[0]}</div>
                    <div>
                        <div class="font-bold text-amber-900">${char.name}</div>
                        <div class="text-xs text-amber-600">${char.type}</div>
                    </div>
                    <div class="ml-3 text-xs bg-amber-200 text-amber-800 px-2 py-1 rounded">UP</div>
                </div>
            `;
            }).join('');
            
            document.getElementById('global-pity-count').textContent = globalPity;
            document.getElementById('global-pity-remain').textContent = Math.max(0, 100 - globalPity);
            document.getElementById('global-pity-bar').style.width = `${Math.min((globalPity / 100) * 100, 100)}%`;
            
            const currentSpecialPity = specialPity[currentPool];
            document.getElementById('special-pity-title').textContent = `${pool.type}保底`;
            document.getElementById('special-pity-desc').textContent = pool.specialPityText;
            document.getElementById('special-pity-count').textContent = currentSpecialPity;
            document.getElementById('special-pity-remain').textContent = Math.max(0, pool.specialPity - currentSpecialPity);
            document.getElementById('special-pity-bar').style.width = `${Math.min((currentSpecialPity / pool.specialPity) * 100, 100)}%`;
            
            document.getElementById('special-rule').textContent = 
                pool.type === '初遇' ? '初遇保底：180抽内必得UP角色' : '重逢保底：180抽内必得未拥有UP角色';
        }

        function gacha(times) {
            const results = [];
            const pool = pools[currentPool];
            
            for (let i = 0; i < times; i++) {
                globalPity++;
                specialPity[currentPool]++;
                let result;
                
                if (specialPity[currentPool] >= pool.specialPity) {
                    if (pool.type === '初遇') {
                        result = { ...pool.upCharacters[0], rarity: 'legend', isUp: true };
                    } else {
                        const unowned = pool.upCharacters.filter(c => !ownedCharacters.has(c.name));
                        const target = unowned.length > 0 ? unowned[Math.floor(Math.random() * unowned.length)] : pool.upCharacters[Math.floor(Math.random() * pool.upCharacters.length)];
                        result = { ...target, rarity: 'legend', isUp: true };
                    }
                    specialPity[currentPool] = 0;
                } else if (globalPity >= 100) {
                    result = getRandomLegend(pool);
                    globalPity = 0;
                } else {
                    const rand = Math.random();
                    if (rand < 0.02) { result = getRandomLegend(pool); globalPity = 0; }
                    else if (rand < 0.22) result = { name: characters.epic[Math.floor(Math.random() * characters.epic.length)], rarity: 'epic' };
                    else if (rand < 0.62) result = { name: characters.elite[Math.floor(Math.random() * characters.elite.length)], rarity: 'elite' };
                    else result = { name: characters.common[Math.floor(Math.random() * characters.common.length)], rarity: 'common' };
                }
                
                if (result.isUp) specialPity[currentPool] = 0;
                if (result.rarity === 'legend') {
                    ownedCharacters.add(result.name);
                    // 更新传说角色统计
                    if (!stats.legendStats[result.name]) {
                        stats.legendStats[result.name] = 0;
                    }
                    stats.legendStats[result.name]++;
                }
                
                results.push(result);
                stats.total++;
                if (result.rarity === 'legend') stats.legend++;
                else if (result.rarity === 'epic') stats.epic++;
                else if (result.rarity === 'elite') stats.elite++;
                else stats.common++;
                
                stats.history.unshift({
                    time: new Date().toLocaleTimeString(),
                    name: result.name,
                    rarity: result.rarity,
                    isUp: result.isUp,
                    pool: pool.name
                });
            }
            
            if (stats.history.length > 50) stats.history = stats.history.slice(0, 50);
            displayResults(results);
            updateStats();
            updateUI();
        }

        function getRandomLegend(pool) {
            const isUp = Math.random() < pool.upRate;
            if (isUp) {
                const upChar = pool.upCharacters[Math.floor(Math.random() * pool.upCharacters.length)];
                return { ...upChar, rarity: 'legend', isUp: true };
            } else {
                const nonUp = characters.legend.filter(c => !c.isUp);
                const char = nonUp[Math.floor(Math.random() * nonUp.length)];
                return { name: char.name, type: char.type || '未知', rarity: 'legend', isUp: false };
            }
        }

        function displayResults(results) {
            const area = document.getElementById('result-area');
            const grid = document.getElementById('result-grid');
            const count = document.getElementById('result-count');
            
            area.classList.remove('hidden');
            count.textContent = `(${results.length}次)`;
            
            grid.innerHTML = results.map((r, i) => {
                const rarityClass = `card-rarity-${r.rarity}`;
                const rarityText = r.rarity === 'legend' ? '传说' : r.rarity === 'epic' ? '史诗' : r.rarity === 'elite' ? '精英' : '普通';
                const upBadge = r.isUp ? '<div class="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] px-1 rounded z-10">UP</div>' : '';
                
                const charInfo = getCharacterInfo(r.name, r.rarity);
                const pixelUrl = charInfo.pixelUrl || `像素人物 ${r.name}.png`;
                
                return `
    <div class="character-card relative ${rarityClass} rounded-lg text-white text-center cursor-pointer transform hover:scale-105 transition flex flex-col items-center justify-between p-0" style="animation-delay: ${i * 0.05}s; min-height: 120px;">
        ${upBadge}
        <div class="rarity-label w-full text-center mb-1">${rarityText}</div>
        <div class="flex-1 flex items-center justify-center w-full">
            <img src="${pixelUrl}" alt="${r.name}" class="pixel-character-img" 
                 onerror="this.style.display='none'; this.parentElement.innerHTML='<div class=\'text-2xl\'>?</div>';">
        </div>
        <div class="character-name w-full text-center mt-1">${r.name}</div>
    </div>
`;
            }).join('');
        }

        function updateStats() {
            document.getElementById('stat-total').textContent = stats.total;
            document.getElementById('stat-legend').textContent = stats.legend;
            document.getElementById('stat-epic').textContent = stats.epic;
            document.getElementById('stat-avg').textContent = stats.legend > 0 ? (stats.total / stats.legend).toFixed(1) : 0;
            
            // 更新历史记录（电脑端）
            const historyList = document.getElementById('history-list');
            if (stats.history.length === 0) {
                historyList.innerHTML = '<div class="text-center text-gray-400 py-8">暂无记录</div>';
            } else {
                historyList.innerHTML = stats.history.map(h => {
                    const colorClass = h.rarity === 'legend' ? 'text-amber-600 font-bold' : h.rarity === 'epic' ? 'text-purple-600' : h.rarity === 'elite' ? 'text-blue-600' : 'text-gray-500';
                    const upMark = h.isUp ? ' <span class="text-red-500 text-xs">[UP]</span>' : '';
                    return `
                        <div class="flex justify-between items-center py-2 border-b border-gray-100 text-sm">
                            <div>
                                <span class="text-gray-400 text-xs mr-2">${h.time}</span>
                                <span class="${colorClass}">${h.name}</span>${upMark}
                            </div>
                            <span class="text-xs text-gray-400">${h.pool}</span>
                        </div>
                    `;
                }).join('');
            }
            
            // 更新历史记录（手机端）
            const historyListMobile = document.getElementById('history-list-mobile');
            if (stats.history.length === 0) {
                historyListMobile.innerHTML = '<div class="text-center text-gray-400 py-8">暂无记录</div>';
            } else {
                historyListMobile.innerHTML = stats.history.map(h => {
                    const colorClass = h.rarity === 'legend' ? 'text-amber-600 font-bold' : h.rarity === 'epic' ? 'text-purple-600' : h.rarity === 'elite' ? 'text-blue-600' : 'text-gray-500';
                    const upMark = h.isUp ? ' <span class="text-red-500 text-xs">[UP]</span>' : '';
                    return `
                        <div class="flex justify-between items-center py-2 border-b border-gray-100 text-sm">
                            <div>
                                <span class="text-gray-400 text-xs mr-2">${h.time}</span>
                                <span class="${colorClass}">${h.name}</span>${upMark}
                            </div>
                            <span class="text-xs text-gray-400">${h.pool}</span>
                        </div>
                    `;
                }).join('');
            }
            
            // 更新传说角色统计
            updateLegendStats();
        }

        function updateLegendStats() {
            const legendStats = stats.legendStats;
            const legendEntries = Object.entries(legendStats);
            
            // 手机端
            const mobileContainer = document.getElementById('legend-stats-list-mobile');
            if (legendEntries.length === 0) {
                mobileContainer.innerHTML = '<div class="text-center text-gray-400 py-8 col-span-2">暂无传说角色</div>';
            } else {
                mobileContainer.innerHTML = legendEntries.map(([name, count]) => {
                    const countDisplay = count > 1 ? `×${count}` : '';
                    return `
                        <div class="flex items-center justify-between p-2 bg-amber-50 rounded border border-amber-200">
                            <span class="text-amber-600 font-semibold text-sm">${name}</span>
                            ${countDisplay ? `<span class="text-amber-600 font-bold text-sm">${countDisplay}</span>` : ''}
                        </div>
                    `;
                }).join('');
            }
            
            // 电脑端
            const desktopContainer = document.getElementById('legend-stats-list-desktop');
            if (legendEntries.length === 0) {
                desktopContainer.innerHTML = '<div class="text-center text-gray-400 py-8 col-span-3">暂无传说角色</div>';
            } else {
                desktopContainer.innerHTML = legendEntries.map(([name, count]) => {
                    const countDisplay = count > 1 ? `×${count}` : '';
                    return `
                        <div class="flex items-center justify-between p-2 bg-amber-50 rounded border border-amber-200">
                            <span class="text-amber-600 font-semibold text-sm">${name}</span>
                            ${countDisplay ? `<span class="text-amber-600 font-bold text-sm">${countDisplay}</span>` : ''}
                        </div>
                    `;
                }).join('');
            }
        }

        function renderCharacterLists() {
            const pool = pools[currentPool];
            const legendContainer = document.getElementById('legend-list');
            let legendHTML = '';
            
            // 获取当前卡池的UP角色名集合
            const currentUpNames = new Set(pool.upCharacters.map(c => c.name));
            
            // 1. 先显示UP角色（按照 pool.upCharacters 的顺序）
            if (pool.type === '初遇') {
                const upChar = pool.upCharacters[0];
                legendHTML += `<div class="flex justify-between items-center p-2 bg-amber-50 rounded border border-amber-200"><span class="font-semibold text-amber-900">${upChar.name} <span class="text-xs bg-red-500 text-white px-1 rounded">UP</span></span><span class="text-amber-700 font-mono">1.000%</span></div>`;
            } else {
                pool.upCharacters.forEach(char => {
                    legendHTML += `<div class="flex justify-between items-center p-2 bg-amber-50 rounded border border-amber-200"><span class="font-semibold text-amber-900">${char.name} <span class="text-xs bg-red-500 text-white px-1 rounded">UP</span></span><span class="text-amber-700 font-mono">0.750%</span></div>`;
                });
            }
            
            // 2. 显示非UP传说角色（按照 LEGEND_NAMES 数组的原始顺序）
            const nonUpRate = pool.type === '初遇' ? '0.014%' : '0.007%';
            LEGEND_NAMES.forEach(name => {
                // 跳过当前卡池的UP角色
                if (!currentUpNames.has(name)) {
                    legendHTML += `<div class="flex justify-between items-center p-2 bg-gray-50 rounded"><span class="text-gray-700">${name}</span><span class="text-gray-500 font-mono text-xs">${nonUpRate}</span></div>`;
                }
            });
            legendContainer.innerHTML = legendHTML;
            
            // 3. 史诗角色（按照 EPIC_NAMES 数组的原始顺序）
            document.getElementById('epic-list').innerHTML = EPIC_NAMES.map(name => `<div class="flex justify-between items-center p-2 bg-gray-50 rounded"><span class="text-gray-700 text-xs">${name}</span><span class="text-gray-500 font-mono text-xs">0.741%</span></div>`).join('');
            
            // 4. 精英角色（按照 ELITE_NAMES 数组的原始顺序）
            document.getElementById('elite-list').innerHTML = ELITE_NAMES.map(name => `<div class="flex justify-between items-center p-2 bg-gray-50 rounded"><span class="text-gray-700 text-xs">${name}</span><span class="text-gray-500 font-mono text-xs">2.222%</span></div>`).join('');
            
            // 5. 普通角色（按照 COMMON_NAMES 数组的原始顺序）
            document.getElementById('common-list').innerHTML = COMMON_NAMES.map(name => `<div class="flex justify-between items-center p-2 bg-gray-50 rounded"><span class="text-gray-700 text-xs">${name}</span><span class="text-gray-500 font-mono text-xs">3.455%</span></div>`).join('');
        }

        function showDetails() { renderCharacterLists(); document.getElementById('details-modal').classList.remove('hidden'); }
        function closeDetails() { document.getElementById('details-modal').classList.add('hidden'); }
        document.getElementById('details-modal').addEventListener('click', function(e) { if (e.target === this) closeDetails(); });

        init();
    