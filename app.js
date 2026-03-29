const defaultPresets = [
  {
    id: "tier30",
    name: "三十档",
    targetTotal: 104,
    supplyTotal: 166,
    bandCaps: { "8-9段": 25, "10段": 4, "11段": 5, "12段": 32, "13段": 13, "14-15段": 3 },
  },
  {
    id: "tier29",
    name: "二十九档",
    targetTotal: 99,
    supplyTotal: 161,
    bandCaps: { "8-9段": 25, "10段": 4, "11段": 5, "12段": 32, "13段": 13, "14-15段": 3 },
  },
  {
    id: "tier28",
    name: "二十八档",
    targetTotal: 92,
    supplyTotal: 155,
    bandCaps: { "8-9段": 25, "10段": 4, "11段": 5, "12段": 32, "13段": 12, "14-15段": 3 },
  },
  {
    id: "tier27",
    name: "二十七档",
    targetTotal: 81,
    supplyTotal: 138,
    bandCaps: { "8-9段": 23, "10段": 3, "11段": 4, "12段": 28, "13段": 12, "14-15段": 3 },
  },
  {
    id: "tier26",
    name: "二十六档",
    targetTotal: 81,
    supplyTotal: 139,
    bandCaps: { "8-9段": 22, "10段": 3, "11段": 4, "12段": 28, "13段": 12, "14-15段": 3 },
  },
];

const bandDefinitions = [
  { name: "8-9段", min: 80, max: 99 },
  { name: "10段", min: 100, max: 109 },
  { name: "11段", min: 110, max: 119 },
  { name: "12段", min: 120, max: 129 },
  { name: "13段", min: 130, max: 139 },
  { name: "14-15段", min: 140, max: 159 },
];

const state = {
  products: [],
  priceRows: [],
  orderRows: [],
  marketRows: [],
  selectedPresetId: defaultPresets[0].id,
};

const els = {
  priceFile: document.querySelector("#priceFile"),
  orderFile: document.querySelector("#orderFile"),
  marketFile: document.querySelector("#marketFile"),
  loadSampleBtn: document.querySelector("#loadSampleBtn"),
  recalcBtn: document.querySelector("#recalcBtn"),
  importSummary: document.querySelector("#importSummary"),
  presetSelect: document.querySelector("#presetSelect"),
  targetTotal: document.querySelector("#targetTotal"),
  supplyTotal: document.querySelector("#supplyTotal"),
  bandTableBody: document.querySelector("#bandTable tbody"),
  marketTableBody: document.querySelector("#marketTable tbody"),
  fillSummary: document.querySelector("#fillSummary"),
  fillTableBody: document.querySelector("#fillTable tbody"),
  optSummary: document.querySelector("#optSummary"),
  optTableBody: document.querySelector("#optTable tbody"),
  profitSummary: document.querySelector("#profitSummary"),
  profitTableBody: document.querySelector("#profitTable tbody"),
  fillRetailBtn: document.querySelector("#fillRetailBtn"),
  clearMarketBtn: document.querySelector("#clearMarketBtn"),
};

function init() {
  populatePresets();
  applyPreset(defaultPresets[0].id);
  bindEvents();
  renderAll();
}

function bindEvents() {
  els.loadSampleBtn.addEventListener("click", () => {
    applyPreset(defaultPresets[0].id);
    renderAll();
  });

  els.recalcBtn.addEventListener("click", renderAll);

  els.presetSelect.addEventListener("change", (event) => {
    applyPreset(event.target.value);
    renderAll();
  });

  els.targetTotal.addEventListener("input", renderAll);
  els.supplyTotal.addEventListener("input", renderAll);

  els.priceFile.addEventListener("change", async (event) => {
    state.priceRows = await readWorkbookRows(event.target.files[0]);
    mergeProducts();
    renderAll();
  });

  els.orderFile.addEventListener("change", async (event) => {
    state.orderRows = await readWorkbookRows(event.target.files[0]);
    mergeProducts();
    renderAll();
  });

  els.marketFile.addEventListener("change", async (event) => {
    state.marketRows = await readWorkbookRows(event.target.files[0]);
    mergeProducts();
    renderAll();
  });

  els.fillRetailBtn.addEventListener("click", () => {
    state.products.forEach((product) => {
      if (Number.isFinite(product.retailPrice)) {
        product.marketPrice = product.retailPrice;
      }
    });
    renderAll();
  });

  els.clearMarketBtn.addEventListener("click", () => {
    state.products.forEach((product) => {
      product.marketPrice = null;
    });
    renderAll();
  });
}

function populatePresets() {
  els.presetSelect.innerHTML = defaultPresets
    .map((preset) => `<option value="${preset.id}">${preset.name}</option>`)
    .join("");
}

function applyPreset(presetId) {
  const preset = defaultPresets.find((item) => item.id === presetId) || defaultPresets[0];
  state.selectedPresetId = preset.id;
  els.presetSelect.value = preset.id;
  els.targetTotal.value = preset.targetTotal;
  els.supplyTotal.value = preset.supplyTotal;

  els.bandTableBody.innerHTML = bandDefinitions
    .map((band) => {
      const cap = preset.bandCaps[band.name] ?? 0;
      return `
        <tr data-band="${band.name}">
          <td>${band.name}</td>
          <td>${band.min}-${band.max}</td>
          <td><input type="number" min="0" step="1" value="${cap}" data-cap-input="${band.name}"></td>
        </tr>
      `;
    })
    .join("");

  els.bandTableBody.querySelectorAll("input").forEach((input) => {
    input.addEventListener("input", renderAll);
  });
}

async function readWorkbookRows(file) {
  if (!file) return [];
  const buffer = await file.arrayBuffer();
  const workbook = XLSX.read(buffer, { type: "array" });
  const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
  return XLSX.utils.sheet_to_json(firstSheet, { header: 1, defval: "" });
}

function mergeProducts() {
  const priceProducts = parsePriceRows(state.priceRows);
  const orderProducts = parseOrderRows(state.orderRows);
  const marketProducts = parseMarketRows(state.marketRows);
  const merged = new Map();

  for (const entry of [...priceProducts, ...orderProducts, ...marketProducts]) {
    const name = normalizeName(entry.name);
    if (!name) continue;
    const current = merged.get(name) || makeEmptyProduct(name);
    merged.set(name, {
      ...current,
      ...entry,
      name,
      retailPrice: coalesceNumber(entry.retailPrice, current.retailPrice),
      wholesalePrice: coalesceNumber(entry.wholesalePrice, current.wholesalePrice),
      maxQty: coalesceNumber(entry.maxQty, current.maxQty),
      orderQty: coalesceNumber(entry.orderQty, current.orderQty),
      demandQty: coalesceNumber(entry.demandQty, current.demandQty),
      orderAmount: coalesceNumber(entry.orderAmount, current.orderAmount),
      marketPrice: coalesceNumber(entry.marketPrice, current.marketPrice),
    });
  }

  state.products = Array.from(merged.values())
    .map((product) => {
      const availableQty = firstFinite(product.maxQty, product.demandQty, product.orderQty, 0);
      return {
        ...product,
        availableQty,
        bandName: getBandName(firstFinite(product.retailPrice, product.marketPrice, 0)),
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
}

function parsePriceRows(rows) {
  if (!rows.length) return [];
  const headerIndex = rows.findIndex((row) => row.some((cell) => includesAny(cell, ["商品", "批发价"])));
  if (headerIndex < 0) return [];
  const header = rows[headerIndex].map(String);
  return rows
    .slice(headerIndex + 1)
    .map((row) => ({
      name: pickCell(row, header, ["商品", "商品名称"]),
      wholesalePrice: toNumber(pickCell(row, header, ["批发价", "批发价格"])),
      retailPrice: toNumber(pickCell(row, header, ["建议零售价", "零售价"])),
    }))
    .filter((item) => item.name);
}

function parseOrderRows(rows) {
  if (!rows.length) return [];
  const headerIndex = rows.findIndex((row) => row.some((cell) => includesAny(cell, ["商品", "订单量"])));
  if (headerIndex < 0) return [];
  const header = rows[headerIndex].map(String);
  return rows
    .slice(headerIndex + 1)
    .map((row) => ({
      name: pickCell(row, header, ["商品", "商品名称"]),
      retailPrice: toNumber(pickCell(row, header, ["建议零售价", "零售价"])),
      wholesalePrice: toNumber(pickCell(row, header, ["批发价", "批发价格"])),
      demandQty: toNumber(pickCell(row, header, ["需求量", "可订量"])),
      orderQty: toNumber(pickCell(row, header, ["订单量"])),
      orderAmount: toNumber(pickCell(row, header, ["金额"])),
      maxQty: toNumber(pickCell(row, header, ["需求量", "可订量"])),
    }))
    .filter((item) => item.name && item.name !== "合计");
}

function parseMarketRows(rows) {
  if (!rows.length) return [];
  const headerIndex = rows.findIndex((row) => row.some((cell) => includesAny(cell, ["商品", "行情价"])));
  if (headerIndex < 0) return [];
  const header = rows[headerIndex].map(String);
  return rows
    .slice(headerIndex + 1)
    .map((row) => ({
      name: pickCell(row, header, ["商品", "商品名称"]),
      marketPrice: toNumber(pickCell(row, header, ["行情价", "市场价", "找货价"])),
    }))
    .filter((item) => item.name);
}

function renderAll() {
  renderImportSummary();
  renderMarketTable();
  renderFillAnalysis();
  renderOptimization();
  renderProfitAnalysis();
}

function renderImportSummary() {
  const totalProducts = state.products.length;
  const orderProducts = state.products.filter((item) => Number.isFinite(item.orderQty) && item.orderQty > 0).length;
  const marketProducts = state.products.filter((item) => Number.isFinite(item.marketPrice)).length;
  els.importSummary.innerHTML = `
    已识别 <strong>${totalProducts}</strong> 个商品，
    其中订单商品 <strong>${orderProducts}</strong> 个，
    已录入行情价 <strong>${marketProducts}</strong> 个。
  `;
}

function renderMarketTable() {
  if (!state.products.length) {
    els.marketTableBody.innerHTML = `<tr><td colspan="6" class="hint">导入价格表或订单表后，这里会出现商品清单。</td></tr>`;
    return;
  }

  els.marketTableBody.innerHTML = state.products
    .map((product, index) => {
      const unitProfit = calcUnitProfit(product);
      return `
        <tr>
          <td>${product.name}</td>
          <td>${formatMoney(product.retailPrice)}</td>
          <td>${formatMoney(product.wholesalePrice)}</td>
          <td>${formatQty(product.availableQty)}</td>
          <td>
            <input
              class="market-input"
              type="number"
              step="0.01"
              value="${Number.isFinite(product.marketPrice) ? product.marketPrice : ""}"
              data-market-index="${index}"
            >
          </td>
          <td class="${unitProfit >= 0 ? "status-ok" : "status-bad"}">${formatMoney(unitProfit)}</td>
        </tr>
      `;
    })
    .join("");

  els.marketTableBody.querySelectorAll("[data-market-index]").forEach((input) => {
    input.addEventListener("input", (event) => {
      const index = Number(event.target.dataset.marketIndex);
      const value = toNumber(event.target.value);
      state.products[index].marketPrice = Number.isFinite(value) ? value : null;
      renderFillAnalysis();
      renderOptimization();
      renderProfitAnalysis();
    });
  });
}

function renderFillAnalysis() {
  const config = getCurrentConfig();
  const candidates = buildUnitCandidates("wholesalePrice");
  const minPlan = buildSelectionPlan(candidates, config, "asc", "wholesalePrice");
  const maxPlan = buildSelectionPlan(candidates, config, "desc", "wholesalePrice");
  const actualOrderQty = sumBy(state.products, (item) => item.orderQty || 0);
  const actualOrderAmount = sumBy(state.products, (item) => item.orderAmount || ((item.orderQty || 0) * (item.wholesalePrice || 0)));

  els.fillSummary.innerHTML = [
    metricCard("目标总条数", `${config.targetTotal}`),
    metricCard("分段上限合计", `${config.totalCap}`),
    metricCard("可参与测算条数", `${candidates.length}`),
    metricCard("实际订单", `${formatQty(actualOrderQty)} 条 / ${formatMoney(actualOrderAmount)} 元`),
  ].join("");

  const rows = [
    {
      label: "满档最低金额",
      qty: minPlan.totalQty,
      amount: minPlan.totalValue,
      note: minPlan.shortage > 0 ? `可订量不足，缺 ${minPlan.shortage} 条` : "按最便宜组合装满目标条数",
    },
    {
      label: "满档最高金额",
      qty: maxPlan.totalQty,
      amount: maxPlan.totalValue,
      note: maxPlan.shortage > 0 ? `可订量不足，缺 ${maxPlan.shortage} 条` : "按最贵组合装满目标条数",
    },
    {
      label: "实际订单",
      qty: actualOrderQty,
      amount: actualOrderAmount,
      note: actualOrderQty >= config.targetTotal ? "已达到或超过目标条数" : `距离目标还差 ${Math.max(config.targetTotal - actualOrderQty, 0)} 条`,
    },
  ];

  els.fillTableBody.innerHTML = rows
    .map((row) => `
      <tr>
        <td>${row.label}</td>
        <td>${formatQty(row.qty)}</td>
        <td>${formatMoney(row.amount)}</td>
        <td>${row.note}</td>
      </tr>
    `)
    .join("");
}

function renderOptimization() {
  const config = getCurrentConfig();
  const candidates = buildUnitCandidates("profit");
  const plan = buildSelectionPlan(candidates, config, "desc", "profit");
  const grouped = groupPlanByProduct(plan.selectedUnits);
  const totalProfit = sumBy(grouped, (item) => item.totalProfit);
  const totalAmount = sumBy(grouped, (item) => item.totalCost);

  els.optSummary.innerHTML = [
    metricCard("推荐条数", `${formatQty(plan.totalQty)} / ${config.targetTotal}`),
    metricCard("推荐金额", `${formatMoney(totalAmount)}`),
    metricCard("预估利润", `${formatMoney(totalProfit)}`),
    metricCard("未满足条数", `${plan.shortage}`),
  ].join("");

  if (!grouped.length) {
    els.optTableBody.innerHTML = `<tr><td colspan="6" class="hint">录入行情价后，这里会给出利润最大化的订货组合。</td></tr>`;
    return;
  }

  els.optTableBody.innerHTML = grouped
    .sort((a, b) => b.totalProfit - a.totalProfit)
    .map((item) => `
      <tr>
        <td>${item.name}</td>
        <td>${item.bandName}</td>
        <td>${formatMoney(item.wholesalePrice)}</td>
        <td>${formatMoney(item.marketPrice)}</td>
        <td>${formatQty(item.qty)}</td>
        <td class="${item.totalProfit >= 0 ? "status-ok" : "status-bad"}">${formatMoney(item.totalProfit)}</td>
      </tr>
    `)
    .join("");
}

function renderProfitAnalysis() {
  const rows = state.products
    .filter((item) => Number.isFinite(item.orderQty) && item.orderQty > 0)
    .map((item) => {
      const unitProfit = calcUnitProfit(item);
      return {
        ...item,
        unitProfit,
        totalProfit: unitProfit * (item.orderQty || 0),
      };
    });

  const totalQty = sumBy(rows, (item) => item.orderQty);
  const totalCost = sumBy(rows, (item) => (item.orderQty || 0) * (item.wholesalePrice || 0));
  const totalProfit = sumBy(rows, (item) => item.totalProfit);

  els.profitSummary.innerHTML = [
    metricCard("订单总条数", `${formatQty(totalQty)}`),
    metricCard("订单总成本", `${formatMoney(totalCost)}`),
    metricCard("订单总盈亏", `${formatMoney(totalProfit)}`),
    metricCard("已覆盖行情价商品", `${rows.filter((item) => Number.isFinite(item.marketPrice)).length}`),
  ].join("");

  if (!rows.length) {
    els.profitTableBody.innerHTML = `<tr><td colspan="6" class="hint">导入订单明细后，这里会按行情价测算盈亏。</td></tr>`;
    return;
  }

  els.profitTableBody.innerHTML = rows
    .sort((a, b) => b.totalProfit - a.totalProfit)
    .map((item) => `
      <tr>
        <td>${item.name}</td>
        <td>${formatQty(item.orderQty)}</td>
        <td>${formatMoney(item.wholesalePrice)}</td>
        <td>${formatMoney(item.marketPrice)}</td>
        <td class="${item.unitProfit >= 0 ? "status-ok" : "status-bad"}">${formatMoney(item.unitProfit)}</td>
        <td class="${item.totalProfit >= 0 ? "status-ok" : "status-bad"}">${formatMoney(item.totalProfit)}</td>
      </tr>
    `)
    .join("");
}

function getCurrentConfig() {
  const targetTotal = toNumber(els.targetTotal.value) || 0;
  const supplyTotal = toNumber(els.supplyTotal.value) || 0;
  const bandCaps = {};
  els.bandTableBody.querySelectorAll("[data-cap-input]").forEach((input) => {
    bandCaps[input.dataset.capInput] = toNumber(input.value) || 0;
  });
  return {
    targetTotal,
    supplyTotal,
    bandCaps,
    totalCap: Object.values(bandCaps).reduce((sum, value) => sum + value, 0),
  };
}

function buildUnitCandidates(metric) {
  return state.products
    .flatMap((product) => {
      const qty = Math.max(0, Math.floor(product.availableQty || 0));
      const bandName = product.bandName;
      if (!qty || !bandName) return [];
      return Array.from({ length: qty }, () => ({
        name: product.name,
        bandName,
        wholesalePrice: firstFinite(product.wholesalePrice, 0),
        marketPrice: product.marketPrice,
        profit: metric === "profit" ? calcUnitProfit(product) : firstFinite(product.wholesalePrice, 0),
      }));
    });
}

function buildSelectionPlan(candidates, config, direction, metric) {
  const sorted = [...candidates].sort((a, b) => {
    const diff = (a[metric] || 0) - (b[metric] || 0);
    if (diff === 0) return a.name.localeCompare(b.name, "zh-CN");
    return direction === "asc" ? diff : -diff;
  });

  const bandCounts = Object.fromEntries(Object.keys(config.bandCaps).map((band) => [band, 0]));
  const selectedUnits = [];

  for (const unit of sorted) {
    if (selectedUnits.length >= config.targetTotal) break;
    const limit = config.bandCaps[unit.bandName] ?? 0;
    if ((bandCounts[unit.bandName] || 0) >= limit) continue;
    selectedUnits.push(unit);
    bandCounts[unit.bandName] = (bandCounts[unit.bandName] || 0) + 1;
  }

  const totalValue = sumBy(selectedUnits, (item) => metric === "profit" ? item.wholesalePrice : item[metric] || 0);
  return {
    selectedUnits,
    totalQty: selectedUnits.length,
    totalValue,
    shortage: Math.max(config.targetTotal - selectedUnits.length, 0),
  };
}

function groupPlanByProduct(selectedUnits) {
  const grouped = new Map();
  selectedUnits.forEach((unit) => {
    const current = grouped.get(unit.name) || {
      name: unit.name,
      bandName: unit.bandName,
      wholesalePrice: unit.wholesalePrice,
      marketPrice: unit.marketPrice,
      qty: 0,
      totalProfit: 0,
      totalCost: 0,
    };
    current.qty += 1;
    current.totalProfit += firstFinite(unit.marketPrice, 0) - firstFinite(unit.wholesalePrice, 0);
    current.totalCost += firstFinite(unit.wholesalePrice, 0);
    grouped.set(unit.name, current);
  });
  return Array.from(grouped.values());
}

function calcUnitProfit(product) {
  if (!Number.isFinite(product.marketPrice) || !Number.isFinite(product.wholesalePrice)) return 0;
  return product.marketPrice - product.wholesalePrice;
}

function metricCard(label, value) {
  return `<div class="metric-card"><span>${label}</span><strong>${value}</strong></div>`;
}

function getBandName(retailPrice) {
  const band = bandDefinitions.find((item) => retailPrice >= item.min && retailPrice <= item.max);
  return band ? band.name : "";
}

function pickCell(row, header, keywords) {
  const index = header.findIndex((title) => keywords.some((keyword) => String(title).includes(keyword)));
  return index >= 0 ? row[index] : "";
}

function includesAny(value, keywords) {
  const text = String(value || "");
  return keywords.some((keyword) => text.includes(keyword));
}

function normalizeName(name) {
  return String(name || "").trim();
}

function makeEmptyProduct(name) {
  return {
    name,
    retailPrice: null,
    wholesalePrice: null,
    maxQty: null,
    orderQty: null,
    demandQty: null,
    orderAmount: null,
    marketPrice: null,
  };
}

function toNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const text = String(value ?? "").replace(/,/g, "").trim();
  if (!text) return null;
  const num = Number(text);
  return Number.isFinite(num) ? num : null;
}

function coalesceNumber(nextValue, currentValue) {
  return Number.isFinite(nextValue) ? nextValue : currentValue;
}

function firstFinite(...values) {
  return values.find((value) => Number.isFinite(value));
}

function sumBy(items, picker) {
  return items.reduce((sum, item) => sum + (picker(item) || 0), 0);
}

function formatMoney(value) {
  if (!Number.isFinite(value)) return "-";
  return value.toFixed(2);
}

function formatQty(value) {
  if (!Number.isFinite(value)) return "-";
  return Number(value).toFixed(0);
}

init();
