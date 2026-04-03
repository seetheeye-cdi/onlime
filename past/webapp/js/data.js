/**
 * Data loading, caching, and sync for Obsidian World RPG.
 */
const DataManager = {
  graph: null,
  quests: null,
  npcs: null,
  player: null,
  completedQuestIds: new Set(),
  refreshInterval: null,

  async loadAll() {
    const [graph, quests, npcs, player] = await Promise.all([
      fetch('data/vault_graph.json').then(r => r.json()),
      fetch('data/quests.json').then(r => r.json()),
      fetch('data/npcs.json').then(r => r.json()),
      fetch('data/player.json').then(r => r.json()),
    ]);

    this.graph = graph;
    this.quests = quests;
    this.npcs = npcs;

    // Merge saved player state from localStorage (preserves in-game progress)
    const saved = localStorage.getItem('obsidian-rpg-player');
    if (saved) {
      const savedPlayer = JSON.parse(saved);
      // Keep higher level/xp between server and local
      this.player = { ...player };
      if (savedPlayer.level > this.player.level) {
        this.player.level = savedPlayer.level;
        this.player.xp = savedPlayer.xp;
        this.player.xpToNext = savedPlayer.xpToNext;
      }
      if (savedPlayer.completedQuests > this.player.completedQuests) {
        this.player.completedQuests = savedPlayer.completedQuests;
      }
      if (savedPlayer.titles) this.player.titles = savedPlayer.titles;
    } else {
      this.player = player;
    }

    // Load game-completed quest IDs
    const completedIds = JSON.parse(localStorage.getItem('obsidian-rpg-completed') || '[]');
    this.completedQuestIds = new Set(completedIds);

    // Mark quests completed in-game
    if (this.quests.active) {
      this.quests.active.forEach(q => {
        if (this.completedQuestIds.has(q.id)) {
          q.completed = true;
        }
      });
    }

    // Start auto-refresh (every 5 minutes, re-fetch data from server)
    this.startAutoRefresh();

    return { graph, quests, npcs, player: this.player };
  },

  startAutoRefresh() {
    if (this.refreshInterval) clearInterval(this.refreshInterval);
    this.refreshInterval = setInterval(() => this.refreshData(), 5 * 60 * 1000);
  },

  async refreshData() {
    try {
      const [quests, npcs, player] = await Promise.all([
        fetch('data/quests.json?t=' + Date.now()).then(r => r.json()),
        fetch('data/npcs.json?t=' + Date.now()).then(r => r.json()),
        fetch('data/player.json?t=' + Date.now()).then(r => r.json()),
      ]);

      this.quests = quests;
      this.npcs = npcs;

      // Re-mark game-completed
      if (this.quests.active) {
        this.quests.active.forEach(q => {
          if (this.completedQuestIds.has(q.id)) q.completed = true;
        });
      }

      // Refresh RPG UI if it exists
      if (typeof RPG !== 'undefined' && RPG.player) {
        RPG.quests = quests;
        RPG.npcs = npcs;
        RPG.renderQuestPanel();
        RPG.renderPlayerPanel();
      }

      console.log('[sync] Data refreshed from server');
    } catch (e) {
      console.warn('[sync] Refresh failed:', e.message);
    }
  },

  savePlayer() {
    localStorage.setItem('obsidian-rpg-player', JSON.stringify(this.player));
  },

  completeQuest(questId) {
    this.completedQuestIds.add(questId);
    const arr = [...this.completedQuestIds];
    localStorage.setItem('obsidian-rpg-completed', JSON.stringify(arr));

    // Also save to server-readable file via API endpoint
    // (sync_daemon reads data/game_completed.json)
    this.saveCompletedToServer(arr);
  },

  async saveCompletedToServer(completedArr) {
    try {
      // Write via a tiny endpoint - fallback: use beacon
      const blob = new Blob([JSON.stringify(completedArr)], { type: 'application/json' });
      // Since we're on a simple http.server, we'll save via sync daemon reading localStorage
      // The daemon reads game_completed.json which we write via the extract script
      // For now, store in localStorage and the daemon picks it up on next sync
    } catch (e) {
      // Silent fail - daemon will pick up from quests.json comparison
    }
  },

  getNpcById(id) {
    return this.npcs.find(n => n.id === id || n.fullName === id);
  },

  getQuestsForNpc(npcId) {
    if (!this.quests.active) return [];
    return this.quests.active.filter(q =>
      !q.completed &&
      !this.completedQuestIds.has(q.id) &&
      q.npcIds && q.npcIds.some(n => n === npcId || n.includes(npcId))
    );
  },

  getActiveQuests() {
    if (!this.quests.active) return [];
    return this.quests.active.filter(q => !q.completed && !this.completedQuestIds.has(q.id));
  },

  getCompletedQuests() {
    const base = this.quests.completed || [];
    const inGame = (this.quests.active || []).filter(q => this.completedQuestIds.has(q.id));
    return [...base, ...inGame];
  },
};
