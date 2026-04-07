/**
 * 3D Knowledge Graph - Obsidian-style wiki-link visualization
 * Nodes = vault notes, Edges = [[wiki-links]]
 * Hover to highlight connections, click to inspect.
 */
const Graph3D = {
  scene: null,
  camera: null,
  renderer: null,
  controls: null,
  raycaster: null,
  mouse: null,
  nodeMeshes: [],
  edgeLines: [],       // individual per-edge LineSegments for highlighting
  nodeMap: {},          // id -> mesh
  nodeDataMap: {},      // id -> node data
  adjacency: {},        // id -> [{target, line}]
  selectedNode: null,
  hoveredNode: null,
  positions: {},
  activeFilters: new Set(),
  labelSprites: [],
  tooltip: null,

  init(container, graphData) {
    this.graphData = graphData;
    this.container = container;
    const width = container.clientWidth;
    const height = container.clientHeight;

    // Scene
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1a1a2e);

    // Camera
    this.camera = new THREE.PerspectiveCamera(55, width / height, 1, 8000);
    this.camera.position.set(0, 150, 600);

    // Renderer
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    // Controls
    this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.rotateSpeed = 0.5;
    this.controls.zoomSpeed = 1.5;
    this.controls.minDistance = 30;
    this.controls.maxDistance = 3000;

    // Raycaster
    this.raycaster = new THREE.Raycaster();
    this.raycaster.params.Points = { threshold: 5 };
    this.mouse = new THREE.Vector2();

    // Lights
    this.scene.add(new THREE.AmbientLight(0x445566, 0.6));
    const point = new THREE.PointLight(0xaabbff, 0.8, 3000);
    point.position.set(0, 400, 0);
    this.scene.add(point);

    // Tooltip
    this.tooltip = document.createElement('div');
    this.tooltip.style.cssText = 'position:fixed;padding:6px 12px;background:rgba(0,0,0,0.92);color:#fff;font:bold 13px sans-serif;border-radius:6px;pointer-events:none;display:none;z-index:999;border:1px solid rgba(255,255,255,0.15)';
    document.body.appendChild(this.tooltip);

    // Build graph
    this.buildAdjacency(graphData);
    this.layoutNodes(graphData);
    this.createNodes(graphData);
    this.createEdges(graphData);
    this.createLabels(graphData);
    this.setupFilters(graphData);
    this.updateInfo(graphData);

    // Events
    this.renderer.domElement.addEventListener('mousemove', e => this.onMouseMove(e));
    this.renderer.domElement.addEventListener('click', e => this.onClick(e));
    window.addEventListener('resize', () => this.onResize());

    const searchInput = document.getElementById('graph-search');
    if (searchInput) {
      searchInput.addEventListener('input', e => this.onSearch(e.target.value));
    }

    this.animate();
  },

  buildAdjacency(data) {
    this.adjacency = {};
    data.edges.forEach(e => {
      if (!this.adjacency[e.source]) this.adjacency[e.source] = [];
      if (!this.adjacency[e.target]) this.adjacency[e.target] = [];
      this.adjacency[e.source].push(e.target);
      this.adjacency[e.target].push(e.source);
    });
  },

  layoutNodes(data) {
    const nodes = data.nodes;
    const edges = data.edges;
    const positions = {};

    // Initialize: cluster by category in a sphere
    const catAngles = {};
    const catKeys = [...new Set(nodes.map(n => n.category))];
    catKeys.forEach((cat, i) => {
      catAngles[cat] = (i / catKeys.length) * Math.PI * 2;
    });

    nodes.forEach(node => {
      const a = catAngles[node.category] || 0;
      const r = 150 + Math.random() * 250;
      const ySpread = (Math.random() - 0.5) * 300;
      positions[node.id] = {
        x: Math.cos(a) * r + (Math.random() - 0.5) * 80,
        y: ySpread,
        z: Math.sin(a) * r + (Math.random() - 0.5) * 80,
        vx: 0, vy: 0, vz: 0,
      };
    });

    // Category centers
    const categoryCenter = {};
    catKeys.forEach((cat, i) => {
      const a = (i / catKeys.length) * Math.PI * 2;
      categoryCenter[cat] = { x: Math.cos(a) * 200, y: 0, z: Math.sin(a) * 200 };
    });

    // Force simulation
    const iterations = 100;
    for (let iter = 0; iter < iterations; iter++) {
      const alpha = 1 - iter / iterations;
      const cooling = Math.pow(alpha, 0.5);

      // Cluster force
      nodes.forEach(node => {
        const pos = positions[node.id];
        const center = categoryCenter[node.category];
        if (center) {
          const str = 0.04 * cooling;
          pos.vx += (center.x - pos.x) * str;
          pos.vy += (center.y - pos.y) * str * 0.5;
          pos.vz += (center.z - pos.z) * str;
        }
      });

      // Repulsion (sampled)
      const sample = Math.min(nodes.length, 300);
      for (let i = 0; i < sample; i++) {
        const pi = positions[nodes[i].id];
        for (let j = i + 1; j < sample; j++) {
          const pj = positions[nodes[j].id];
          const dx = pi.x - pj.x, dy = pi.y - pj.y, dz = pi.z - pj.z;
          const dist2 = dx * dx + dy * dy + dz * dz + 1;
          const force = (400 * cooling) / dist2;
          pi.vx += dx * force; pi.vy += dy * force; pi.vz += dz * force;
          pj.vx -= dx * force; pj.vy -= dy * force; pj.vz -= dz * force;
        }
      }

      // Edge attraction (stronger to pull linked nodes together)
      edges.forEach(e => {
        const ps = positions[e.source], pt = positions[e.target];
        if (!ps || !pt) return;
        const dx = pt.x - ps.x, dy = pt.y - ps.y, dz = pt.z - ps.z;
        const str = 0.02 * cooling;
        ps.vx += dx * str; ps.vy += dy * str; ps.vz += dz * str;
        pt.vx -= dx * str; pt.vy -= dy * str; pt.vz -= dz * str;
      });

      // Apply + damp
      nodes.forEach(node => {
        const p = positions[node.id];
        p.x += p.vx; p.y += p.vy; p.z += p.vz;
        p.vx *= 0.75; p.vy *= 0.75; p.vz *= 0.75;
      });
    }

    this.positions = positions;
  },

  createNodes(data) {
    data.nodes.forEach(node => {
      const pos = this.positions[node.id];
      if (!pos) return;

      const size = Math.min(6, Math.max(1.2, node.size * 1.2));
      const color = new THREE.Color(node.color);

      const geo = new THREE.SphereGeometry(size, 12, 10);
      const mat = new THREE.MeshPhongMaterial({
        color, emissive: color, emissiveIntensity: 0.4,
        transparent: true, opacity: 0.9,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(pos.x, pos.y, pos.z);
      mesh.userData = node;
      mesh.userData._baseColor = node.color;
      mesh.userData._baseOpacity = 0.9;
      mesh.userData._baseEmissive = 0.4;

      this.scene.add(mesh);
      this.nodeMeshes.push(mesh);
      this.nodeMap[node.id] = mesh;
      this.nodeDataMap[node.id] = node;
    });
  },

  createEdges(data) {
    // Create individual edge lines for per-edge highlighting
    const baseMat = new THREE.LineBasicMaterial({ color: 0x8899bb, transparent: true, opacity: 0.35 });

    data.edges.forEach(e => {
      const ps = this.positions[e.source];
      const pt = this.positions[e.target];
      if (!ps || !pt) return;

      const geo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(ps.x, ps.y, ps.z),
        new THREE.Vector3(pt.x, pt.y, pt.z),
      ]);
      const line = new THREE.LineSegments(geo, baseMat.clone());
      line.userData = { source: e.source, target: e.target };
      this.scene.add(line);
      this.edgeLines.push(line);

      // Register in adjacency with line reference
      if (!this.adjacency[e.source]) this.adjacency[e.source] = [];
      if (!this.adjacency[e.target]) this.adjacency[e.target] = [];
    });

    // Build edge lookup: nodeId -> [line]
    this.nodeEdges = {};
    this.edgeLines.forEach(line => {
      const { source, target } = line.userData;
      if (!this.nodeEdges[source]) this.nodeEdges[source] = [];
      if (!this.nodeEdges[target]) this.nodeEdges[target] = [];
      this.nodeEdges[source].push(line);
      this.nodeEdges[target].push(line);
    });
  },

  createLabels(data) {
    // Show labels for nodes with high degree (top nodes by connections)
    const threshold = 3;
    data.nodes
      .filter(n => (n.degree || 0) >= threshold)
      .forEach(node => {
        const pos = this.positions[node.id];
        if (!pos) return;
        const sprite = this.makeLabel(node.name, node.color);
        sprite.position.set(pos.x, pos.y + (node.size || 1) * 2 + 4, pos.z);
        sprite.userData = { nodeId: node.id };
        this.scene.add(sprite);
        this.labelSprites.push(sprite);
      });
  },

  makeLabel(text, color) {
    const c = document.createElement('canvas');
    const ctx = c.getContext('2d');
    c.width = 512; c.height = 64;

    ctx.font = 'bold 24px sans-serif';
    const w = Math.min(ctx.measureText(text).width + 24, 500);

    ctx.fillStyle = 'rgba(0,0,0,0.75)';
    this.roundRect(ctx, (512 - w) / 2, 8, w, 44, 8);
    ctx.fill();

    ctx.fillStyle = color || '#ffffff';
    ctx.textAlign = 'center';
    ctx.fillText(text, 256, 40);

    const tex = new THREE.CanvasTexture(c);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
    sprite.scale.set(30, 4, 1);
    return sprite;
  },

  roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r); ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h); ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r); ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y); ctx.closePath();
  },

  // === Highlight on hover (Obsidian-style) ===
  highlightNode(mesh) {
    const nodeId = mesh.userData.id;

    // Dim everything
    this.nodeMeshes.forEach(m => {
      m.material.opacity = 0.06;
      m.material.emissiveIntensity = 0.05;
    });
    this.edgeLines.forEach(l => {
      l.material.opacity = 0.05;
      l.material.color.set(0x8899bb);
    });
    this.labelSprites.forEach(s => { s.material.opacity = 0.1; });

    // Highlight hovered node
    mesh.material.opacity = 1.0;
    mesh.material.emissiveIntensity = 0.9;
    mesh.scale.set(1.5, 1.5, 1.5);

    // Highlight connected nodes + edges
    const connectedIds = new Set();
    const edges = this.nodeEdges[nodeId] || [];
    edges.forEach(line => {
      const { source, target } = line.userData;
      const otherId = source === nodeId ? target : source;
      connectedIds.add(otherId);

      // Brighten edge
      line.material.opacity = 0.7;
      line.material.color.set(mesh.userData._baseColor);
    });

    connectedIds.forEach(id => {
      const m = this.nodeMap[id];
      if (m) {
        m.material.opacity = 0.95;
        m.material.emissiveIntensity = 0.6;
      }
    });

    // Brighten labels of connected nodes
    this.labelSprites.forEach(s => {
      if (s.userData.nodeId === nodeId || connectedIds.has(s.userData.nodeId)) {
        s.material.opacity = 1.0;
      }
    });
  },

  resetHighlight() {
    this.nodeMeshes.forEach(m => {
      m.material.opacity = m.userData._baseOpacity || 0.9;
      m.material.emissiveIntensity = m.userData._baseEmissive || 0.4;
      m.scale.set(1, 1, 1);
    });
    this.edgeLines.forEach(l => {
      l.material.opacity = 0.35;
      l.material.color.set(0x8899bb);
    });
    this.labelSprites.forEach(s => { s.material.opacity = 1.0; });
  },

  // === Filters ===
  setupFilters(data) {
    const filtersDiv = document.getElementById('graph-filters');
    if (!filtersDiv) return;

    const categories = data.categories || {};
    filtersDiv.innerHTML = '';

    Object.entries(categories)
      .sort((a, b) => b[1] - a[1])
      .forEach(([cat, count]) => {
        const chip = document.createElement('button');
        chip.className = 'filter-chip active';
        chip.textContent = `${cat} (${count})`;
        chip.dataset.category = cat;
        this.activeFilters.add(cat);

        chip.addEventListener('click', () => {
          chip.classList.toggle('active');
          if (this.activeFilters.has(cat)) {
            this.activeFilters.delete(cat);
          } else {
            this.activeFilters.add(cat);
          }
          this.applyFilters();
        });

        filtersDiv.appendChild(chip);
      });
  },

  applyFilters() {
    this.nodeMeshes.forEach(mesh => {
      mesh.visible = this.activeFilters.has(mesh.userData.category);
    });
    this.labelSprites.forEach(s => {
      const nodeData = this.nodeDataMap[s.userData.nodeId];
      s.visible = nodeData ? this.activeFilters.has(nodeData.category) : false;
    });
    this.edgeLines.forEach(line => {
      const sNode = this.nodeDataMap[line.userData.source];
      const tNode = this.nodeDataMap[line.userData.target];
      line.visible = sNode && tNode && this.activeFilters.has(sNode.category) && this.activeFilters.has(tNode.category);
    });
  },

  updateInfo(data) {
    const info = document.getElementById('graph-info');
    if (info) info.textContent = `${data.totalNodes} nodes \u2022 ${data.totalEdges} edges`;
  },

  // === Interaction ===
  onMouseMove(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    this.raycaster.setFromCamera(this.mouse, this.camera);
    const intersects = this.raycaster.intersectObjects(this.nodeMeshes);

    if (this.hoveredNode && (!intersects.length || intersects[0].object !== this.hoveredNode)) {
      this.resetHighlight();
      this.hoveredNode = null;
      this.renderer.domElement.style.cursor = 'default';
      this.tooltip.style.display = 'none';
    }

    if (intersects.length > 0 && intersects[0].object.visible) {
      const mesh = intersects[0].object;
      if (mesh !== this.hoveredNode) {
        this.hoveredNode = mesh;
        this.highlightNode(mesh);
        this.renderer.domElement.style.cursor = 'pointer';
      }
      // Tooltip follows mouse
      const node = mesh.userData;
      const deg = node.degree || 0;
      const folder = node.folder || '';
      this.tooltip.innerHTML = `<strong>${node.name}</strong><br><span style="font-size:11px;color:#aaa">${folder}</span><br><span style="font-size:11px;color:#8af">${node.category} \u2022 ${deg} connections</span>`;
      this.tooltip.style.display = 'block';
      this.tooltip.style.left = (event.clientX + 14) + 'px';
      this.tooltip.style.top = (event.clientY - 10) + 'px';
    }
  },

  onClick() {
    if (!this.hoveredNode) {
      document.getElementById('node-panel')?.classList.remove('visible');
      this.selectedNode = null;
      return;
    }
    this.selectedNode = this.hoveredNode.userData;
    this.showNodePanel(this.hoveredNode.userData);
  },

  showNodePanel(node) {
    const panel = document.getElementById('node-panel');
    if (!panel) return;

    // Find connected nodes
    const connected = [];
    this.graphData.edges.forEach(e => {
      if (e.source === node.id) {
        const n = this.nodeDataMap[e.target];
        if (n) connected.push(n);
      } else if (e.target === node.id) {
        const n = this.nodeDataMap[e.source];
        if (n) connected.push(n);
      }
    });

    // Sort by degree
    connected.sort((a, b) => (b.degree || 0) - (a.degree || 0));

    panel.innerHTML = `
      <h3 style="margin:0 0 8px;font-size:16px">${node.name}</h3>
      <div class="node-meta"><span style="color:${node.color}">\u25CF</span> ${node.category} \u2022 ${node.folder}</div>
      ${node.type ? `<div class="node-meta">Type: ${node.type}</div>` : ''}
      ${node.created ? `<div class="node-meta">Created: ${node.created}</div>` : ''}
      <div class="node-meta" style="color:var(--gold);font-weight:700">${node.degree || 0} connections</div>
      ${connected.length > 0 ? `
        <div class="node-links">
          <div style="font-size:11px;color:var(--text-muted);margin:10px 0 6px;text-transform:uppercase;letter-spacing:1px">Linked Notes (${connected.length})</div>
          ${connected.slice(0, 30).map(n => `
            <span class="node-link" data-id="${n.id}" style="border-left:3px solid ${n.color};display:block;padding:4px 8px;margin-bottom:3px;cursor:pointer;font-size:12px;background:rgba(255,255,255,0.03);border-radius:0 4px 4px 0">${n.name} <span style="color:#666;font-size:10px">${n.category}</span></span>
          `).join('')}
          ${connected.length > 30 ? `<span style="font-size:11px;color:var(--text-muted)">...+${connected.length - 30} more</span>` : ''}
        </div>
      ` : ''}
    `;

    panel.querySelectorAll('.node-link').forEach(el => {
      el.addEventListener('click', () => {
        const mesh = this.nodeMap[el.dataset.id];
        if (mesh) {
          this.flyTo(mesh.position);
          this.highlightNode(mesh);
          this.hoveredNode = mesh;
          this.showNodePanel(mesh.userData);
        }
      });
    });

    panel.classList.add('visible');
  },

  flyTo(position) {
    const target = new THREE.Vector3(position.x, position.y, position.z);
    const offset = new THREE.Vector3(40, 25, 40);
    const destination = target.clone().add(offset);
    const start = this.camera.position.clone();
    const startTarget = this.controls.target.clone();
    const startTime = Date.now();

    const anim = () => {
      const t = Math.min(1, (Date.now() - startTime) / 700);
      const ease = t * (2 - t);
      this.camera.position.lerpVectors(start, destination, ease);
      this.controls.target.lerpVectors(startTarget, target, ease);
      this.controls.update();
      if (t < 1) requestAnimationFrame(anim);
    };
    anim();
  },

  onSearch(query) {
    if (!query) {
      this.resetHighlight();
      return;
    }

    const q = query.toLowerCase();
    let found = null;

    this.nodeMeshes.forEach(mesh => {
      const node = mesh.userData;
      const matches = node.name.toLowerCase().includes(q) ||
                     (node.folder || '').toLowerCase().includes(q) ||
                     (node.tags || []).some(t => String(t).toLowerCase().includes(q));
      mesh.material.opacity = matches ? 1.0 : 0.04;
      mesh.material.emissiveIntensity = matches ? 0.8 : 0.05;
      if (matches && !found) found = mesh;
    });

    this.edgeLines.forEach(l => { l.material.opacity = 0.03; });
    this.labelSprites.forEach(s => { s.material.opacity = 0.1; });

    if (found) {
      this.flyTo(found.position);
      // Also highlight its labels
      this.labelSprites.forEach(s => {
        if (s.userData.nodeId === found.userData.id) s.material.opacity = 1.0;
      });
    }
  },

  onResize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  },

  animate() {
    requestAnimationFrame(() => this.animate());
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  },
};
