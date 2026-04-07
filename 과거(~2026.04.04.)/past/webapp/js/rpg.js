/**
 * RPG Quest System - Obsidian World
 * 2D top-down Canvas (Gather Town style). Player WASD movement. Guild zones.
 */
const RPG = {
  player: null,
  npcs: [],
  quests: null,
  selectedGuild: null,

  // Canvas 2D
  canvas: null,
  ctx: null,
  camera: { x: 0, y: 0 },
  entities: [],
  playerEntity: null,
  nearestNpc: null,
  lastTime: 0,
  time: 0,

  // Input
  keys: { w: false, a: false, s: false, d: false, arrowup: false, arrowdown: false, arrowleft: false, arrowright: false },
  playerSpeed: 160,
  playerTarget: null,
  hoveredNpc: null,

  // World geometry
  walls: [],
  furniture: [],
  zones: [],
  paths: [],

  GUILD_ICONS: {
    fish: '\u{1F41F}', robot: '\u{1F916}', trophy: '\u{1F3C6}',
    book: '\u{1F4DA}', star: '\u{2B50}', scroll: '\u{1F4DC}',
  },

  SHIRT_COLORS: ['#7B8FB2','#8DB89E','#C49494','#B3A081','#8B7EB4','#6FABC2','#D89A6C','#A5B4A1','#C193B4','#93B9C1','#B9A57E','#A899B9'],
  SKIN_COLORS: ['#FFDCB2','#F5C8A8','#E8B89D','#D4A088','#C49070'],
  HAIR_COLORS: ['#2C1810','#4A3728','#1A1A2E','#5C4033','#8B6914'],
  PANTS_COLORS: ['#4A4A5A','#3A3A48','#5A5060','#484858'],

  GUILD_ZONES: {
    "참치상사":  { cx: -500, cy: -500, size: 400, color: '#FF6B6B', floor: '#FFD4D4' },
    "에이아이당": { cx:  500, cy: -500, size: 400, color: '#339AF0', floor: '#CCE5FF' },
    "더해커톤":  { cx: -500, cy:  500, size: 400, color: '#51CF66', floor: '#D4F5D4' },
    "넥스트노벨": { cx:  500, cy:  500, size: 400, color: '#CC5DE8', floor: '#F0D4FF' },
    "자기계발":  { cx:    0, cy:    0, size: 400, color: '#FFD43B', floor: '#FFF3CC' },
  },

  SPECIAL_ROOMS: {
    philosopher: { cx:    0, cy: -900, size: 320, color: '#8B7355', floor: '#F0E6D4', label: "현자의 서재" },
    mogul:       { cx:  900, cy:    0, size: 320, color: '#C0C0C0', floor: '#E8E8F0', label: "거인의 어깨" },
    artist:      { cx: -900, cy:    0, size: 320, color: '#E8A0BF', floor: '#FFE4F0', label: "뮤즈의 정원" },
    fictional:   { cx:    0, cy:  900, size: 320, color: '#88DDFF', floor: '#E0F4FF', label: "상상의 방" },
  },

  // ── INIT ──────────────────────────────────────────────────────────────────

  init(playerData, npcsData, questsData) {
    this.player = playerData;
    this.npcs = npcsData;
    this.quests = questsData;

    this.renderPlayerPanel();
    this.initGameWorld();
    this.renderQuestPanel();
  },

  initGameWorld() {
    const container = document.getElementById('game-world');
    if (!container) return;

    this.canvas = document.createElement('canvas');
    this.canvas.width = container.clientWidth || 800;
    this.canvas.height = container.clientHeight || 600;
    this.canvas.style.display = 'block';
    this.canvas.style.width = '100%';
    this.canvas.style.height = '100%';
    container.appendChild(this.canvas);

    this.ctx = this.canvas.getContext('2d');

    this.buildWorld();
    this.placeCharacters();

    // Mouse events
    this.canvas.addEventListener('mousemove', e => this.onMouseMove(e));
    this.canvas.addEventListener('click', e => this.onClick(e));

    // Keyboard events
    document.addEventListener('keydown', e => {
      const k = e.key.toLowerCase();
      if (k in this.keys) { this.keys[k] = true; e.preventDefault(); }
      if (k === 'e' || k === 'enter') { this.interactNearest(); }
    });
    document.addEventListener('keyup', e => {
      const k = e.key.toLowerCase();
      if (k in this.keys) this.keys[k] = false;
    });

    window.addEventListener('resize', () => this.onResize());

    this.lastTime = performance.now();
    requestAnimationFrame(ts => this.gameLoop(ts));
  },

  // ── WORLD BUILDING ────────────────────────────────────────────────────────

  buildWorld() {
    this.paths = [
      // Horizontal cross
      { x: -700, y: -60, w: 1400, h: 120 },
      // Vertical cross
      { x: -60, y: -700, w: 120, h: 1400 },
      // To philosopher (north)
      { x: -60, y: -900, w: 120, h: 260 },
      // To fictional (south)
      { x: -60, y: 640, w: 120, h: 260 },
      // To artist (west)
      { x: -900, y: -60, w: 260, h: 120 },
      // To mogul (east)
      { x: 640, y: -60, w: 260, h: 120 },
    ];

    this.zones = [];

    // Guild zones
    Object.entries(this.GUILD_ZONES).forEach(([name, z]) => {
      this.zones.push({
        x: z.cx - z.size / 2, y: z.cy - z.size / 2,
        w: z.size, h: z.size,
        color: z.color, floor: z.floor,
        label: name, isGuild: true,
      });
    });

    // Special rooms
    Object.entries(this.SPECIAL_ROOMS).forEach(([, r]) => {
      this.zones.push({
        x: r.cx - r.size / 2, y: r.cy - r.size / 2,
        w: r.size, h: r.size,
        color: r.color, floor: r.floor,
        label: r.label, isGuild: false,
      });
    });

    this.furniture = [];

    // Guild zone furniture
    Object.entries(this.GUILD_ZONES).forEach(([, z]) => {
      const { cx, cy } = z;
      const isCenter = cx === 0 && cy === 0;
      if (isCenter) {
        // Meeting table
        this.furniture.push({ type: 'table_round', x: cx, y: cy, r: 28 });
        // Plants
        [[-70, -70], [70, 70], [70, -70], [-70, 70]].forEach(([dx, dy]) => {
          this.furniture.push({ type: 'plant', x: cx + dx, y: cy + dy });
        });
        // Sofas
        this.furniture.push({ type: 'sofa', x: cx - 50, y: cy + 40, w: 40, h: 18 });
        this.furniture.push({ type: 'sofa', x: cx + 50, y: cy + 40, w: 40, h: 18 });
      } else {
        // Desks 3×2
        for (let r = 0; r < 3; r++) {
          for (let c = 0; c < 2; c++) {
            const dx = (c - 0.5) * 60;
            const dy = (r - 1) * 55;
            this.furniture.push({ type: 'desk', x: cx + dx, y: cy + dy, w: 44, h: 22 });
          }
        }
        // Meeting table in corner
        const mtx = cx + (cx < 0 ? 90 : -90);
        const mty = cy + (cy < 0 ? 90 : -90);
        this.furniture.push({ type: 'table_round', x: mtx, y: mty, r: 20 });
        // Plants
        this.furniture.push({ type: 'plant', x: cx + (cx < 0 ? -110 : 110), y: cy + (cy < 0 ? -110 : 110) });
        this.furniture.push({ type: 'plant', x: cx + (cx < 0 ? -110 : 110), y: cy + (cy < 0 ? 90 : -90) });
      }
    });

    // Special room furniture
    Object.entries(this.SPECIAL_ROOMS).forEach(([cat, r]) => {
      const { cx, cy } = r;
      if (cat === 'philosopher') {
        // Bookshelves
        for (let i = 0; i < 3; i++) {
          this.furniture.push({ type: 'bookshelf', x: cx - 70 + i * 60, y: cy - 100, w: 44, h: 18 });
        }
        // Reading desk
        this.furniture.push({ type: 'desk', x: cx, y: cy + 20, w: 50, h: 24 });
        // Candle
        this.furniture.push({ type: 'candle', x: cx + 30, y: cy - 10 });
      } else if (cat === 'mogul') {
        // Large desk
        this.furniture.push({ type: 'desk', x: cx, y: cy, w: 70, h: 32 });
        // Globe
        this.furniture.push({ type: 'globe', x: cx + 80, y: cy - 60 });
        // Bookshelf
        this.furniture.push({ type: 'bookshelf', x: cx - 70, y: cy - 80, w: 44, h: 18 });
      } else if (cat === 'artist') {
        // Easels
        for (let i = 0; i < 3; i++) {
          this.furniture.push({ type: 'easel', x: cx - 60 + i * 60, y: cy - 60 });
        }
        // Plants
        for (let i = 0; i < 3; i++) {
          this.furniture.push({ type: 'plant', x: cx - 60 + i * 60, y: cy + 90 });
        }
      } else if (cat === 'fictional') {
        // Portal ring
        this.furniture.push({ type: 'portal', x: cx, y: cy - 40, r: 36 });
        // Crystals
        for (let i = 0; i < 4; i++) {
          const angle = (i / 4) * Math.PI * 2;
          this.furniture.push({ type: 'crystal', x: cx + Math.cos(angle) * 60, y: cy + Math.sin(angle) * 60 });
        }
      }
    });
  },

  // ── CHARACTER PLACEMENT ───────────────────────────────────────────────────

  placeCharacters() {
    this.entities = [];

    const activeQuests = DataManager.getActiveQuests();
    const npcQuestMap = {};
    activeQuests.forEach(q => {
      (q.npcIds || []).forEach(id => {
        if (id === '최동인') return;
        if (!npcQuestMap[id]) npcQuestMap[id] = [];
        npcQuestMap[id].push(q);
      });
    });

    // Quest-giver guild mapping
    const questGuildNpc = {};
    activeQuests.forEach(q => {
      if (q.guild && q.npcIds) {
        q.npcIds.forEach(id => { questGuildNpc[id] = q.guild; });
      }
    });

    // Player entity
    const seed = this.hashStr('최동인');
    this.playerEntity = {
      x: 0, y: 0,
      dir: 0,
      walkFrame: 0, walkTimer: 0,
      colors: {
        skin: this.SKIN_COLORS[seed % this.SKIN_COLORS.length],
        hair: this.HAIR_COLORS[seed % this.HAIR_COLORS.length],
        shirt: '#EEEEEE',
        pants: this.PANTS_COLORS[seed % this.PANTS_COLORS.length],
      },
      isPlayer: true,
      name: '최동인',
    };
    this.entities.push(this.playerEntity);

    // Separate NPCs
    const specialNpcs = {};
    const contactNpcs = [];
    const seen = new Set();

    const allNpcs = this.npcs
      .filter(n => {
        if (n.id === '최동인' || seen.has(n.id)) return false;
        seen.add(n.id);
        return true;
      })
      .sort((a, b) => {
        const aq = (npcQuestMap[a.id] || []).length;
        const bq = (npcQuestMap[b.id] || []).length;
        return bq - aq || b.meetingCount - a.meetingCount;
      });

    allNpcs.forEach(npc => {
      const cat = npc.category || 'contact';
      if (cat !== 'contact' && this.SPECIAL_ROOMS[cat]) {
        if (!specialNpcs[cat]) specialNpcs[cat] = [];
        specialNpcs[cat].push(npc);
      } else {
        contactNpcs.push(npc);
      }
    });

    // Distribute contacts into guild zones
    const guildNpcs = {};
    const unassigned = [];
    contactNpcs.slice(0, 50).forEach(npc => {
      const guild = questGuildNpc[npc.id] || null;
      if (guild && this.GUILD_ZONES[guild]) {
        if (!guildNpcs[guild]) guildNpcs[guild] = [];
        guildNpcs[guild].push(npc);
      } else {
        unassigned.push(npc);
      }
    });

    const guildNames = Object.keys(this.GUILD_ZONES);
    unassigned.forEach((npc, i) => {
      const g = guildNames[i % guildNames.length];
      if (!guildNpcs[g]) guildNpcs[g] = [];
      guildNpcs[g].push(npc);
    });

    // Place guild NPCs
    Object.entries(guildNpcs).forEach(([guild, npcs]) => {
      const zone = this.GUILD_ZONES[guild];
      this.placeNpcsInZone(npcs, { cx: zone.cx, cy: zone.cy }, npcQuestMap, guild);
    });

    // Place special room NPCs
    Object.entries(specialNpcs).forEach(([cat, npcs]) => {
      const room = this.SPECIAL_ROOMS[cat];
      this.placeNpcsInZone(npcs, { cx: room.cx, cy: room.cy }, npcQuestMap, cat);
    });
  },

  placeNpcsInZone(npcs, zone, npcQuestMap, zoneName) {
    npcs.forEach((npc, i) => {
      const hasQuest = !!npcQuestMap[npc.id]?.length;
      const angle = (i / Math.max(npcs.length, 1)) * Math.PI * 2;
      const radius = 40 + (i % 3) * 30;
      const sx = zone.cx + Math.cos(angle) * radius + (Math.random() - 0.5) * 20;
      const sy = zone.cy + Math.sin(angle) * radius + (Math.random() - 0.5) * 20;

      const s = this.hashStr(npc.id);
      const entity = {
        x: sx, y: sy,
        dir: 0,
        walkFrame: 0, walkTimer: 0,
        colors: {
          skin: this.SKIN_COLORS[s % this.SKIN_COLORS.length],
          hair: this.HAIR_COLORS[s % this.HAIR_COLORS.length],
          shirt: this.SHIRT_COLORS[s % this.SHIRT_COLORS.length],
          pants: this.PANTS_COLORS[s % this.PANTS_COLORS.length],
        },
        isPlayer: false,
        name: npc.displayName,
        data: npc,
        quests: npcQuestMap[npc.id] || [],
        hasQuest,
        guild: zoneName,
        homeZone: { x: zone.cx, y: zone.cy },
        state: hasQuest ? 'approaching' : 'idle',
        target: { x: sx, y: sy },
        speed: 50 + Math.random() * 30,
        idleTimer: Math.random() * 5,
        isWalking: hasQuest,
      };
      this.entities.push(entity);
    });
  },

  // ── GAME LOOP ─────────────────────────────────────────────────────────────

  gameLoop(timestamp) {
    const dt = Math.min((timestamp - this.lastTime) / 1000, 0.1);
    this.lastTime = timestamp;
    this.time += dt;

    this.update(dt);
    this.render();

    requestAnimationFrame(ts => this.gameLoop(ts));
  },

  // ── UPDATE ────────────────────────────────────────────────────────────────

  update(dt) {
    this.updatePlayer(dt);
    this.updateCamera(dt);

    const npcEntities = this.entities.filter(e => !e.isPlayer);
    npcEntities.forEach((e, i) => this.updateNpcAI(e, dt, i));

    // Find nearest NPC
    const px = this.playerEntity.x, py = this.playerEntity.y;
    let nearest = null, nearDist = 60;
    npcEntities.forEach(e => {
      const d = Math.sqrt((e.x - px) ** 2 + (e.y - py) ** 2);
      if (d < nearDist) { nearDist = d; nearest = e; }
    });
    this.nearestNpc = nearest;
  },

  updatePlayer(dt) {
    const p = this.playerEntity;
    if (!p) return;

    let dx = 0, dy = 0;
    if (this.keys.w || this.keys.arrowup)    dy -= 1;
    if (this.keys.s || this.keys.arrowdown)  dy += 1;
    if (this.keys.a || this.keys.arrowleft)  dx -= 1;
    if (this.keys.d || this.keys.arrowright) dx += 1;

    let moving = dx !== 0 || dy !== 0;

    // Click-to-move
    if (this.playerTarget && !moving) {
      const tdx = this.playerTarget.x - p.x;
      const tdy = this.playerTarget.y - p.y;
      const dist = Math.sqrt(tdx * tdx + tdy * tdy);
      if (dist > 4) {
        dx = tdx / dist;
        dy = tdy / dist;
        moving = true;
      } else {
        this.playerTarget = null;
      }
    }

    if (moving) {
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      const nx = dx / len, ny = dy / len;
      const spd = this.playerSpeed * dt;

      // Try X movement
      const newX = p.x + nx * spd;
      if (!this.collidesWithWall(newX, p.y, 10)) p.x = newX;

      // Try Y movement
      const newY = p.y + ny * spd;
      if (!this.collidesWithWall(p.x, newY, 10)) p.y = newY;

      // Clamp to world bounds
      p.x = Math.max(-950, Math.min(950, p.x));
      p.y = Math.max(-950, Math.min(950, p.y));

      // Direction
      if (Math.abs(dy) > Math.abs(dx)) {
        p.dir = dy > 0 ? 0 : 1;
      } else if (dx !== 0) {
        p.dir = dx < 0 ? 2 : 3;
      }

      // Walk animation
      p.walkTimer -= dt;
      if (p.walkTimer <= 0) {
        p.walkFrame = 1 - p.walkFrame;
        p.walkTimer = 0.2;
      }
      p.isWalking = true;
    } else {
      p.isWalking = false;
    }
  },

  updateCamera(dt) {
    const p = this.playerEntity;
    if (!p) return;
    const factor = 1 - Math.pow(1 - 0.08, dt * 60);
    this.camera.x += (p.x - this.camera.x) * factor;
    this.camera.y += (p.y - this.camera.y) * factor;
  },

  updateNpcAI(npc, dt, i) {
    const p = this.playerEntity;
    if (!p) return;

    if (npc.state === 'approaching') {
      const dx = p.x - npc.x + ((i % 3) - 1) * 18;
      const dy = p.y - npc.y + ((i % 2) === 0 ? -22 : 22);
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist > 28) {
        const spd = npc.speed * 1.2 * dt;
        const nx = npc.x + (dx / dist) * spd;
        const ny = npc.y + (dy / dist) * spd;
        npc.x = nx; npc.y = ny;
        if (Math.abs(dy) > Math.abs(dx)) {
          npc.dir = dy > 0 ? 0 : 1;
        } else {
          npc.dir = dx < 0 ? 2 : 3;
        }
        npc.isWalking = true;
      } else {
        // Face player
        const ddx = p.x - npc.x, ddy = p.y - npc.y;
        if (Math.abs(ddy) > Math.abs(ddx)) npc.dir = ddy > 0 ? 0 : 1;
        else npc.dir = ddx < 0 ? 2 : 3;
        npc.state = 'waiting';
        npc.isWalking = false;
      }
    } else if (npc.state === 'waiting') {
      const dx = p.x - npc.x, dy = p.y - npc.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (Math.abs(dy) > Math.abs(dx)) npc.dir = dy > 0 ? 0 : 1;
      else npc.dir = dx < 0 ? 2 : 3;
      if (dist > 80) {
        npc.state = 'approaching';
        npc.isWalking = true;
      } else {
        npc.isWalking = false;
      }
    } else {
      // Idle: wander
      npc.idleTimer -= dt;
      if (npc.idleTimer <= 0) {
        if (npc.isWalking) {
          npc.isWalking = false;
          npc.idleTimer = 2 + Math.random() * 4;
        } else {
          const hz = npc.homeZone;
          npc.target = {
            x: hz.x + (Math.random() - 0.5) * 200,
            y: hz.y + (Math.random() - 0.5) * 200,
          };
          npc.isWalking = true;
          npc.idleTimer = 3 + Math.random() * 5;
        }
      }

      if (npc.isWalking && npc.target) {
        const dx = npc.target.x - npc.x;
        const dy = npc.target.y - npc.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist > 4) {
          const spd = npc.speed * dt;
          npc.x += (dx / dist) * spd;
          npc.y += (dy / dist) * spd;
          if (Math.abs(dy) > Math.abs(dx)) npc.dir = dy > 0 ? 0 : 1;
          else npc.dir = dx < 0 ? 2 : 3;
        } else {
          npc.isWalking = false;
          npc.idleTimer = 2 + Math.random() * 3;
        }
      }
    }

    // Walk animation
    if (npc.isWalking) {
      npc.walkTimer -= dt;
      if (npc.walkTimer <= 0) {
        npc.walkFrame = 1 - npc.walkFrame;
        npc.walkTimer = 0.2;
      }
    }
  },

  collidesWithWall(x, y, r) {
    // Simple world-boundary walls only; rooms are open
    if (x < -950 || x > 950 || y < -950 || y > 950) return true;
    return false;
  },

  // ── RENDER ────────────────────────────────────────────────────────────────

  render() {
    const ctx = this.ctx;
    const cw = this.canvas.width, ch = this.canvas.height;

    // Clear
    ctx.fillStyle = '#E8E0D4';
    ctx.fillRect(0, 0, cw, ch);

    ctx.save();
    ctx.translate(cw / 2 - this.camera.x, ch / 2 - this.camera.y);

    // 1. Paths
    ctx.fillStyle = '#D4CBC0';
    this.paths.forEach(p => {
      ctx.fillRect(p.x, p.y, p.w, p.h);
    });

    // 2. Zones
    this.zones.forEach(z => {
      // Floor
      ctx.fillStyle = z.floor;
      ctx.fillRect(z.x, z.y, z.w, z.h);

      // Border
      ctx.strokeStyle = z.color;
      ctx.lineWidth = 3;
      ctx.strokeRect(z.x, z.y, z.w, z.h);

      // Label
      ctx.save();
      ctx.font = 'bold 16px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      // Label background
      const labelW = ctx.measureText(z.label).width + 16;
      ctx.fillStyle = 'rgba(255,255,255,0.75)';
      this.roundRect(ctx, z.x + z.w / 2 - labelW / 2, z.y + 10, labelW, 24, 6);
      ctx.fill();
      ctx.fillStyle = z.color;
      ctx.fillText(z.label, z.x + z.w / 2, z.y + 22);
      ctx.restore();
    });

    // 3. Furniture
    this.drawFurniture(ctx);

    // 4. Characters depth-sorted by Y
    const allChars = this.entities.slice().sort((a, b) => a.y - b.y);
    allChars.forEach(e => this.drawCharacter(ctx, e, e.isPlayer));

    // 5. Interaction prompt
    if (this.nearestNpc) {
      const n = this.nearestNpc;
      ctx.save();
      ctx.font = 'bold 13px sans-serif';
      ctx.textAlign = 'center';
      const promptText = '[E] 대화하기';
      const pw = ctx.measureText(promptText).width + 14;
      const px = n.x, py = n.y - 54;
      ctx.fillStyle = 'rgba(0,0,0,0.8)';
      this.roundRect(ctx, px - pw / 2, py - 11, pw, 22, 6);
      ctx.fill();
      ctx.fillStyle = '#FFD700';
      ctx.fillText(promptText, px, py + 0);
      ctx.restore();
    }

    ctx.restore();
  },

  drawFurniture(ctx) {
    this.furniture.forEach(f => {
      ctx.save();
      switch (f.type) {
        case 'desk':
          // Desk surface
          ctx.fillStyle = '#C4A882';
          ctx.fillRect(f.x - f.w / 2, f.y - f.h / 2, f.w, f.h);
          ctx.strokeStyle = '#8B6914';
          ctx.lineWidth = 1.5;
          ctx.strokeRect(f.x - f.w / 2, f.y - f.h / 2, f.w, f.h);
          // Monitor
          ctx.fillStyle = '#2A2A3A';
          ctx.fillRect(f.x - 8, f.y - f.h / 2 - 10, 16, 11);
          ctx.fillStyle = '#3A5A8A';
          ctx.fillRect(f.x - 7, f.y - f.h / 2 - 9, 14, 9);
          break;

        case 'table_round':
          ctx.fillStyle = '#B8926A';
          ctx.beginPath();
          ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = '#8B6914';
          ctx.lineWidth = 2;
          ctx.stroke();
          break;

        case 'plant': {
          // Pot
          ctx.fillStyle = '#8B5E3C';
          ctx.fillRect(f.x - 7, f.y - 5, 14, 10);
          // Leaves
          ctx.fillStyle = '#4CAF50';
          ctx.beginPath();
          ctx.arc(f.x, f.y - 10, 10, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = '#388E3C';
          ctx.beginPath();
          ctx.arc(f.x - 5, f.y - 14, 7, 0, Math.PI * 2);
          ctx.fill();
          ctx.beginPath();
          ctx.arc(f.x + 5, f.y - 14, 7, 0, Math.PI * 2);
          ctx.fill();
          break;
        }

        case 'sofa':
          ctx.fillStyle = '#7B6B8A';
          ctx.fillRect(f.x - f.w / 2, f.y - f.h / 2, f.w, f.h);
          ctx.fillStyle = '#6A5A78';
          ctx.fillRect(f.x - f.w / 2, f.y - f.h / 2, f.w, 6);
          ctx.strokeStyle = '#5A4A68';
          ctx.lineWidth = 1;
          ctx.strokeRect(f.x - f.w / 2, f.y - f.h / 2, f.w, f.h);
          break;

        case 'bookshelf':
          ctx.fillStyle = '#8B6914';
          ctx.fillRect(f.x - f.w / 2, f.y - f.h / 2, f.w, f.h);
          // Book spines
          const bookColors = ['#C0392B','#2980B9','#27AE60','#8E44AD','#E67E22'];
          for (let bi = 0; bi < 5; bi++) {
            ctx.fillStyle = bookColors[bi % bookColors.length];
            ctx.fillRect(f.x - f.w / 2 + 4 + bi * 7, f.y - f.h / 2 + 3, 5, f.h - 6);
          }
          break;

        case 'globe':
          ctx.fillStyle = '#2196F3';
          ctx.beginPath();
          ctx.arc(f.x, f.y, 14, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = '#1565C0';
          ctx.lineWidth = 1;
          ctx.stroke();
          // Stand
          ctx.strokeStyle = '#8B6914';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(f.x, f.y + 14);
          ctx.lineTo(f.x, f.y + 20);
          ctx.stroke();
          break;

        case 'easel': {
          // Canvas frame
          ctx.fillStyle = '#FFFFF0';
          ctx.fillRect(f.x - 12, f.y - 18, 24, 20);
          ctx.strokeStyle = '#8B6914';
          ctx.lineWidth = 2;
          ctx.strokeRect(f.x - 12, f.y - 18, 24, 20);
          // Legs
          ctx.beginPath();
          ctx.moveTo(f.x - 10, f.y + 2);
          ctx.lineTo(f.x - 14, f.y + 14);
          ctx.moveTo(f.x + 10, f.y + 2);
          ctx.lineTo(f.x + 14, f.y + 14);
          ctx.strokeStyle = '#8B6914';
          ctx.lineWidth = 1.5;
          ctx.stroke();
          break;
        }

        case 'portal': {
          // Glowing ring
          const grad = ctx.createRadialGradient(f.x, f.y, f.r - 8, f.x, f.y, f.r + 8);
          grad.addColorStop(0, 'rgba(136,221,255,0.6)');
          grad.addColorStop(0.5, 'rgba(100,180,255,0.4)');
          grad.addColorStop(1, 'rgba(80,150,255,0)');
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(f.x, f.y, f.r + 8, 0, Math.PI * 2);
          ctx.fill();
          // Ring border
          ctx.strokeStyle = '#88DDFF';
          ctx.lineWidth = 3;
          ctx.beginPath();
          ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2);
          ctx.stroke();
          // Inner glow, animated
          ctx.fillStyle = `rgba(136,221,255,${0.12 + Math.sin(this.time * 2) * 0.06})`;
          ctx.beginPath();
          ctx.arc(f.x, f.y, f.r - 3, 0, Math.PI * 2);
          ctx.fill();
          break;
        }

        case 'crystal': {
          const h = 16, w = 7;
          ctx.fillStyle = `rgba(136,221,255,${0.5 + Math.sin(this.time * 3 + f.x) * 0.2})`;
          ctx.beginPath();
          ctx.moveTo(f.x, f.y - h);
          ctx.lineTo(f.x + w, f.y);
          ctx.lineTo(f.x, f.y + h / 3);
          ctx.lineTo(f.x - w, f.y);
          ctx.closePath();
          ctx.fill();
          ctx.strokeStyle = '#88DDFF';
          ctx.lineWidth = 1;
          ctx.stroke();
          break;
        }

        case 'candle':
          // Candle body
          ctx.fillStyle = '#FFFFF0';
          ctx.fillRect(f.x - 3, f.y - 10, 6, 12);
          // Flame
          ctx.fillStyle = `rgba(255,200,50,${0.8 + Math.sin(this.time * 8) * 0.2})`;
          ctx.beginPath();
          ctx.ellipse(f.x, f.y - 13, 3, 5, 0, 0, Math.PI * 2);
          ctx.fill();
          break;

        default:
          break;
      }
      ctx.restore();
    });
  },

  drawCharacter(ctx, entity, isPlayer) {
    const { x, y, dir, walkFrame, colors, name } = entity;

    // Sizes
    const bodyW = 14, bodyH = 12;
    const headR = 8;
    const legW = 5, legH = 8;

    ctx.save();
    ctx.translate(x, y);

    // Shadow
    ctx.fillStyle = 'rgba(0,0,0,0.18)';
    ctx.beginPath();
    ctx.ellipse(0, 6, 10, 5, 0, 0, Math.PI * 2);
    ctx.fill();

    // Player glow
    if (isPlayer) {
      ctx.shadowColor = '#FFD700';
      ctx.shadowBlur = 14;
    }

    // Leg offset from walk animation
    const legAnim = walkFrame === 1 ? 2 : 0;

    // Legs (pants)
    ctx.fillStyle = colors.pants;
    // Left leg
    const lLegOffset = entity.isWalking ? (walkFrame === 0 ? -2 : 0) : 0;
    const rLegOffset = entity.isWalking ? (walkFrame === 0 ? 0 : -2) : 0;
    ctx.fillRect(-bodyW / 2 + 1, bodyH / 2 - 2 + lLegOffset, legW, legH);
    ctx.fillRect(bodyW / 2 - legW - 1, bodyH / 2 - 2 + rLegOffset, legW, legH);

    // Body (shirt)
    ctx.shadowBlur = 0;
    ctx.fillStyle = colors.shirt;
    ctx.fillRect(-bodyW / 2, -bodyH / 2, bodyW, bodyH);

    // Head (skin)
    ctx.fillStyle = colors.skin;
    this.roundRect(ctx, -headR, -bodyH / 2 - headR * 2 + 2, headR * 2, headR * 2, 4);
    ctx.fill();

    // Hair (direction-dependent)
    ctx.fillStyle = colors.hair;
    if (dir === 1) {
      // Facing up: full hair coverage
      this.roundRect(ctx, -headR, -bodyH / 2 - headR * 2 + 2, headR * 2, headR * 2 - 2, 4);
      ctx.fill();
    } else {
      // Facing down/left/right: hair on top half
      this.roundRect(ctx, -headR, -bodyH / 2 - headR * 2 + 2, headR * 2, headR - 2, 4);
      ctx.fill();
    }

    // Eyes (only for down/left/right)
    if (dir !== 1) {
      ctx.fillStyle = '#1A1A1A';
      if (dir === 0) {
        // Down: eyes in center-lower of head
        ctx.fillRect(-4, -bodyH / 2 - headR + 6, 3, 3);
        ctx.fillRect(2, -bodyH / 2 - headR + 6, 3, 3);
      } else if (dir === 2) {
        // Left: single eye on left
        ctx.fillRect(-headR + 2, -bodyH / 2 - headR + 6, 3, 3);
      } else if (dir === 3) {
        // Right: single eye on right
        ctx.fillRect(headR - 5, -bodyH / 2 - headR + 6, 3, 3);
      }
    }

    // Player gold border
    if (isPlayer) {
      ctx.strokeStyle = '#FFD700';
      ctx.lineWidth = 2;
      ctx.strokeRect(-bodyW / 2 - 1, -bodyH / 2 - 1, bodyW + 2, bodyH + 2);
    }

    ctx.shadowBlur = 0;

    // Name label
    if (name) {
      const labelY = -bodyH / 2 - headR * 2 - 10;
      ctx.font = '10px sans-serif';
      const tw = ctx.measureText(name).width;
      const lw = tw + 10, lh = 16;
      const lx = -lw / 2, ly = labelY - lh;

      ctx.fillStyle = 'rgba(255,255,255,0.9)';
      this.roundRect(ctx, lx, ly, lw, lh, 4);
      ctx.fill();

      ctx.fillStyle = '#222222';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(name, 0, ly + lh / 2);
    }

    // Quest mark: gold "!" with bounce
    if (entity.hasQuest) {
      const bounce = Math.sin(this.time * 3) * 3;
      const qy = -bodyH / 2 - headR * 2 - 28 + bounce;
      ctx.font = 'bold 16px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#FFD700';
      ctx.shadowColor = '#FFD700';
      ctx.shadowBlur = 8;
      ctx.fillText('!', 0, qy);
      ctx.shadowBlur = 0;
    }

    ctx.restore();
  },

  // ── INTERACTION ───────────────────────────────────────────────────────────

  onMouseMove(e) {
    const rect = this.canvas.getBoundingClientRect();
    const sx = (e.clientX - rect.left) * (this.canvas.width / rect.width);
    const sy = (e.clientY - rect.top) * (this.canvas.height / rect.height);
    const world = this.screenToWorld(sx, sy);

    let hit = null;
    const npcEntities = this.entities.filter(en => !en.isPlayer);
    for (const en of npcEntities) {
      const dx = en.x - world.x, dy = en.y - world.y;
      if (Math.sqrt(dx * dx + dy * dy) < 20) {
        hit = en;
        break;
      }
    }
    this.hoveredNpc = hit;
    this.canvas.style.cursor = hit ? 'pointer' : 'default';
  },

  onClick(e) {
    const rect = this.canvas.getBoundingClientRect();
    const sx = (e.clientX - rect.left) * (this.canvas.width / rect.width);
    const sy = (e.clientY - rect.top) * (this.canvas.height / rect.height);
    const world = this.screenToWorld(sx, sy);

    if (this.hoveredNpc) {
      this.openNpcDialog(this.hoveredNpc.data, this.hoveredNpc.quests);
      return;
    }
    // Click-to-move
    this.playerTarget = { x: world.x, y: world.y };
  },

  interactNearest() {
    if (!this.nearestNpc) return;
    const dlg = document.getElementById('dialog-overlay');
    if (dlg && dlg.classList.contains('visible')) return;
    this.openNpcDialog(this.nearestNpc.data, this.nearestNpc.quests);
  },

  screenToWorld(sx, sy) {
    return {
      x: sx - this.canvas.width / 2 + this.camera.x,
      y: sy - this.canvas.height / 2 + this.camera.y,
    };
  },

  onResize() {
    const c = document.getElementById('game-world');
    if (!c || !this.canvas) return;
    this.canvas.width = c.clientWidth || 800;
    this.canvas.height = c.clientHeight || 600;
  },

  // ── PLAYER PANEL ──────────────────────────────────────────────────────────

  renderPlayerPanel() {
    const panel = document.getElementById('player-panel');
    if (!panel) return;
    const p = this.player;
    const xpPct = (p.xp / (p.xp + p.xpToNext)) * 100;
    panel.innerHTML = `
      <div class="player-avatar">\u{1F451}</div>
      <div class="player-name">${p.name}</div>
      <div class="player-title">${p.titles?.[0] || '\uC2E0\uC785 \uBAA8\uD5D8\uAC00'}</div>
      <div class="player-class">${p.class} \u2022 ${p.guilds?.length || 0} Guilds</div>
      <div class="xp-section">
        <div class="xp-header"><span class="level-badge">LV.${p.level}</span><span>${p.xp}/${p.xp+p.xpToNext} XP</span></div>
        <div class="xp-bar-bg"><div class="xp-bar-fill" style="width:${xpPct}%"></div></div>
      </div>
      <div class="stats-section"><h4>STATS</h4>
        ${Object.entries(p.stats||{}).map(([k,v])=>`<div class="stat-row"><span class="stat-name">${{leadership:'\uB9AC\uB354\uC2ED',networking:'\uB124\uD2B8\uC6CC\uD0B9',execution:'\uC2E4\uD589\uB825',vision:'\uBE44\uC820',creativity:'\uCC3D\uC758\uC131'}[k]||k}</span><div class="stat-bar-bg"><div class="stat-bar-fill" style="width:${v*10}%"></div></div><span class="stat-val">${v}</span></div>`).join('')}
      </div>
      <div class="guild-section"><h4 style="font-size:12px;color:var(--text-muted);margin-bottom:10px;text-transform:uppercase;letter-spacing:1px;">GUILDS</h4>
        ${Object.entries(this.quests.guilds||{}).map(([nm,info])=>{const cnt=DataManager.getActiveQuests().filter(q=>q.guild===nm).length;const ic=this.GUILD_ICONS[info.icon]||'\u{1F4DC}';return`<div class="guild-item" data-guild="${nm}"><div class="guild-icon" style="background:${info.color}20;color:${info.color}">${ic}</div><span class="guild-name">${nm}</span>${cnt?`<span class="guild-count">${cnt}</span>`:''}</div>`;}).join('')}
      </div>
      <div style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border)">
        <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">QUEST LOG</div>
        <div style="font-size:24px;font-weight:900;color:var(--gold)">${p.completedQuests}</div>
        <div style="font-size:11px;color:var(--text-muted)">\uC644\uB8CC\uB41C \uD038\uC2A4\uD2B8</div>
      </div>
      <div style="margin-top:12px;font-size:10px;color:var(--text-muted);text-align:center">WASD / \uBC29\uD5A5\uD0A4 / \uD074\uB9AD\uC73C\uB85C \uC774\uB3D9 | E \uB610\uB294 Enter\uB85C \uB300\uD654</div>
    `;
    panel.querySelectorAll('.guild-item').forEach(el=>{el.addEventListener('click',()=>{this.selectedGuild=this.selectedGuild===el.dataset.guild?null:el.dataset.guild;this.renderQuestPanel();});});
  },

  // ── NPC DIALOG ────────────────────────────────────────────────────────────

  openNpcDialog(npc, quests) {
    const overlay = document.getElementById('dialog-overlay');
    const icons = {engineer:'\u{1F4BB}',investor:'\u{1F4B0}',politician:'\u{1F3DB}',founder:'\u{1F680}',designer:'\u{1F3A8}',scholar:'\u{1F393}',merchant:'\u{1F465}'};
    document.getElementById('dialog-npc-portrait').innerHTML = icons[npc.class]||'\u{1F465}';
    document.getElementById('dialog-npc-name').textContent = npc.displayName;
    document.getElementById('dialog-npc-affiliation').textContent = npc.affiliation||'';

    const textEl = document.getElementById('dialog-text');
    const questInfo = document.getElementById('dialog-quest-info');
    const actions = document.getElementById('dialog-actions');

    if (quests.length) {
      textEl.textContent = [`\uB300\uD45C\uB2D8, \uBD80\uD0C1\uB4DC\uB9B4 \uC77C\uC774 ${quests.length}\uAC74 \uC788\uC2B5\uB2C8\uB2E4.`,`\uC774\uAC83 \uC880 \uBD10\uC8FC\uC138\uC694. ${quests.length}\uAC1C\uC758 \uD038\uC2A4\uD2B8\uC785\uB2C8\uB2E4.`,`\uD568\uAED8 \uD574\uC57C \uD560 \uC77C\uC774 \uC788\uC2B5\uB2C8\uB2E4!`][Math.floor(Math.random()*3)];
      questInfo.style.display='block';
      questInfo.innerHTML=quests.map(q=>`<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;padding:10px;background:var(--bg-secondary);border-radius:8px"><span class="quest-difficulty ${q.difficulty}" style="font-size:9px;padding:2px 5px">${q.difficulty}</span><span style="flex:1;font-size:13px">${q.title}</span><span style="color:var(--gold);font-size:11px;font-weight:700">+${q.xp}XP</span><button class="dialog-btn primary" style="padding:4px 12px;font-size:11px" data-qid="${q.id}" data-xp="${q.xp}">\uC644\uB8CC</button></div>`).join('');
      questInfo.querySelectorAll('button[data-qid]').forEach(btn=>{btn.addEventListener('click',e=>{e.stopPropagation();this.completeQuest(btn.dataset.qid,parseInt(btn.dataset.xp));btn.closest('div').style.opacity='0.3';btn.textContent='\u2713';btn.disabled=true;});});
    } else if (npc.bio && npc.bio.trim()) {
      // Show vault note content
      const catLabels = {philosopher:'현자',mogul:'거인',artist:'예술가',fictional:'가상인물'};
      const greeting = catLabels[npc.category]
        ? `"${npc.displayName}"의 기록입니다.`
        : `안녕하세요, 대표님. 현재 별다른 용건은 없습니다.`;
      textEl.textContent = greeting;
      questInfo.style.display = 'block';
      questInfo.innerHTML = `<div style="max-height:200px;overflow-y:auto;padding:12px;background:var(--bg-secondary);border-radius:8px;border-left:3px solid ${npc.category === 'philosopher' ? '#8B7355' : npc.category === 'mogul' ? '#C0C0C0' : npc.category === 'artist' ? '#E8A0BF' : npc.category === 'fictional' ? '#88DDFF' : 'var(--border)'}">
        ${npc.bio.split('\n').filter(l => l.trim()).map(l => `<p style="margin:0 0 8px;line-height:1.7;font-size:13px;color:var(--text-secondary)">${this.escapeHtml(l)}</p>`).join('')}
      </div>`;
    } else {
      textEl.textContent = '\uC548\uB155\uD558\uC138\uC694! \uD604\uC7AC \uBCC4\uB2E4\uB978 \uC6A9\uAC74\uC740 \uC5C6\uC2B5\uB2C8\uB2E4.';
      questInfo.style.display = 'none';
    }
    actions.innerHTML=`<button class="dialog-btn" onclick="RPG.closeDialog()">\uB2EB\uAE30</button>`;
    overlay.classList.add('visible');
  },

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  closeDialog() { document.getElementById('dialog-overlay').classList.remove('visible'); },

  // ── QUEST PANEL ───────────────────────────────────────────────────────────

  renderQuestPanel() {
    const list = document.querySelector('.quest-list');
    if (!list) return;
    const tab = document.querySelector('.quest-tab.active')?.dataset.tab||'active';
    if (tab==='epic'){this.renderEpicQuests(list);return;}
    let quests = tab==='active'?DataManager.getActiveQuests():DataManager.getCompletedQuests();
    if (this.selectedGuild) quests=quests.filter(q=>q.guild===this.selectedGuild);
    if (!quests.length){list.innerHTML=`<div style="text-align:center;padding:40px;color:var(--text-muted)">${tab==='active'?'\uBAA8\uB4E0 \uD038\uC2A4\uD2B8 \uC644\uB8CC! \u{1F389}':'\uC644\uB8CC\uB41C \uD038\uC2A4\uD2B8\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4'}</div>`;return;}
    list.innerHTML=quests.map(q=>{const gi=(this.quests.guilds||{})[q.guild];return`<div class="quest-card"><div class="quest-card-header"><span class="quest-difficulty ${q.difficulty}">${q.difficulty}</span><span class="quest-title">${q.title}</span><span class="quest-xp">+${q.xp}XP</span></div><div class="quest-meta">${q.guild?`<span class="quest-guild-tag" style="background:${gi?.color||'#555'}30;color:${gi?.color||'#888'}">${q.guild}</span>`:``}${q.date?`<span>${q.date}</span>`:``}${q.npcIds?.length?`<span>\u{1F464} ${q.npcIds.join(', ')}</span>`:``}</div>${tab==='active'?`<button class="quest-complete-btn" data-qid="${q.id}" data-xp="${q.xp}">\u2714</button>`:``}</div>`;}).join('');
    list.querySelectorAll('.quest-complete-btn').forEach(btn=>{btn.addEventListener('click',e=>{e.stopPropagation();this.completeQuest(btn.dataset.qid,parseInt(btn.dataset.xp));btn.closest('.quest-card').style.opacity='0.3';setTimeout(()=>this.renderQuestPanel(),500);});});
  },

  renderEpicQuests(list) {
    list.innerHTML=(this.quests.epics||[]).map(e=>{const gi=(this.quests.guilds||{})[e.guild];return`<div class="epic-card"><div class="quest-card-header"><span class="quest-difficulty ${e.difficulty}">${e.difficulty}</span><span class="quest-title">${e.title}</span><span class="quest-xp">+${e.xp}XP</span></div><div style="font-size:12px;color:var(--text-secondary);margin:8px 0">${e.description}</div><div class="quest-meta">${e.guild?`<span class="quest-guild-tag" style="background:${gi?.color||'#555'}30;color:${gi?.color||'#888'}">${e.guild}</span>`:``}</div><div class="epic-progress-bar"><div class="epic-progress-fill" style="width:${e.progress}%"></div></div></div>`;}).join('');
  },

  // ── QUEST COMPLETION ──────────────────────────────────────────────────────

  completeQuest(qid, xp) {
    DataManager.completeQuest(qid);
    this.player.xp += xp;
    const oldLv = this.player.level;
    while (this.player.xp >= this.player.xpToNext) {
      this.player.xp -= this.player.xpToNext;
      this.player.level++;
      this.player.xpToNext = Math.floor(100 * Math.pow(1.2, this.player.level - 1));
    }
    this.player.completedQuests++;
    DataManager.savePlayer();
    this.showXpPopup(xp);
    if (this.player.level > oldLv) this.showLevelUp();
    this.renderPlayerPanel();
  },

  showXpPopup(xp) {
    const el = document.createElement('div');
    el.className = 'xp-popup'; el.textContent = `+${xp} XP`;
    el.style.left = '50%'; el.style.top = '50%';
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 1500);
  },

  showLevelUp() {
    const o = document.getElementById('levelup-overlay');
    if (!o) return;
    const titles = [[1,'\uC2E0\uC785 \uBAA8\uD5D8\uAC00'],[3,'\uC219\uB828\uB41C \uC804\uB7B5\uAC00'],[5,'\uB2A5\uC219\uD55C \uC0AC\uC5C5\uAC00'],[8,'\uC804\uC124\uC758 \uB9AC\uB354'],[12,'\uC138\uACC4\uB97C \uBC14\uAFB8\uB294 \uC790'],[20,'CEO of CEOs']];
    let title='\uC2E0\uC785 \uBAA8\uD5D8\uAC00';
    for (const [l,t] of titles) if (this.player.level>=l) title=t;
    this.player.titles=[title];
    o.innerHTML=`<div class="levelup-content"><div class="levelup-text">LEVEL UP!</div><div class="levelup-level">${this.player.level}</div><div class="levelup-title">${title}</div></div>`;
    o.classList.add('visible');
    setTimeout(()=>o.classList.remove('visible'),2500);
  },

  // ── UTILITIES ─────────────────────────────────────────────────────────────

  hashStr(s) { let h = 0; for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0; return Math.abs(h); },

  roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r); ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h); ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r); ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y); ctx.closePath();
  },
};
