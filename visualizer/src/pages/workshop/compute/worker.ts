import init, {
  computeCorrMatrix,
  computeDepth,
  computeEffRealized,
  computeLeadLag,
  computeMarkout,
  computeMid,
  computeObsBeta,
  computeOffset,
  computeOfi,
  computePairSpread,
  computeQueueImbalance,
  computeSeasonality,
  computeSpread,
} from '../../../../wasm_compute/wasm_compute.js';
import { TaskOutput, WorkerRequest, WorkerResponse } from './types.ts';

let ready: Promise<void> | null = null;

function ensureReady(): Promise<void> {
  if (ready === null) {
    ready = init().then(() => undefined);
  }
  return ready;
}

function runTask(request: WorkerRequest): TaskOutput {
  const { task } = request;
  switch (task.kind) {
    case 'mid': {
      const meta = { productsAllowed: task.input.productsAllowed, products: task.input.products };
      const output = computeMid(
        meta,
        task.input.times,
        task.input.mids,
        task.input.bid1 ?? undefined,
        task.input.ask1 ?? undefined,
        task.input.bidVol1 ?? undefined,
        task.input.askVol1 ?? undefined,
      );
      return { kind: 'mid', output };
    }
    case 'spread': {
      const meta = { productsAllowed: task.input.productsAllowed, products: task.input.products };
      const output = computeSpread(meta, task.input.times, task.input.bid1, task.input.ask1);
      return { kind: 'spread', output };
    }
    case 'depth': {
      const { ladder, productFilter, products, times } = task.input;
      const levelCount = ladder.length;
      const rowCount = products.length;
      // Flatten bid/ask volumes into a single Float64Array: level-major.
      const hasBidMask = new Uint8Array(levelCount);
      const hasAskMask = new Uint8Array(levelCount);
      let anyBid = false;
      let anyAsk = false;
      for (let l = 0; l < levelCount; l += 1) {
        hasBidMask[l] = ladder[l].bidVolume ? 1 : 0;
        hasAskMask[l] = ladder[l].askVolume ? 1 : 0;
        if (hasBidMask[l]) anyBid = true;
        if (hasAskMask[l]) anyAsk = true;
      }
      const bidFlat = anyBid ? new Float64Array(levelCount * rowCount) : undefined;
      const askFlat = anyAsk ? new Float64Array(levelCount * rowCount) : undefined;
      if (bidFlat) for (let l = 0; l < levelCount; l += 1) {
        const src = ladder[l].bidVolume;
        if (src) bidFlat.set(src, l * rowCount);
      }
      if (askFlat) for (let l = 0; l < levelCount; l += 1) {
        const src = ladder[l].askVolume;
        if (src) askFlat.set(src, l * rowCount);
      }
      const output = computeDepth(
        { productFilter, products, maxPoints: task.input.maxPoints },
        times,
        bidFlat,
        askFlat,
        levelCount,
        hasBidMask,
        hasAskMask,
      );
      return { kind: 'depth', output };
    }
    case 'queueImbalance': {
      const meta = {
        productsAllowed: task.input.productsAllowed,
        products: task.input.products,
        horizon: task.input.horizon,
        maxScatter: task.input.maxScatter,
        bins: task.input.bins,
      };
      const output = computeQueueImbalance(meta, task.input.mids, task.input.bidVol1, task.input.askVol1);
      return { kind: 'queueImbalance', output };
    }
    case 'ofi': {
      const meta = {
        productsAllowed: task.input.productsAllowed,
        products: task.input.products,
        maxScatter: task.input.maxScatter,
      };
      const output = computeOfi(
        meta,
        task.input.mids,
        task.input.bid1,
        task.input.bidVol1,
        task.input.ask1,
        task.input.askVol1,
      );
      return { kind: 'ofi', output };
    }
    case 'markout': {
      const meta = {
        tradeProducts: task.input.tradeProducts,
        tradeBuyers: task.input.tradeBuyers,
        tradeSellers: task.input.tradeSellers,
        priceProducts: task.input.priceProducts,
        horizonTimestamps: Array.from(task.input.horizonTimestamps),
        productsAllowed: task.input.productsAllowed,
        counterpartiesAllowed: task.input.counterpartiesAllowed,
      };
      const output = computeMarkout(
        meta,
        task.input.tradeTimes,
        task.input.tradePrices,
        task.input.tradeQuantities,
        task.input.priceTimes,
        task.input.priceMids,
      );
      return { kind: 'markout', output };
    }
    case 'offset': {
      const meta = {
        tradeProducts: task.input.tradeProducts,
        tradeBuyers: task.input.tradeBuyers,
        tradeSellers: task.input.tradeSellers,
        priceProducts: task.input.priceProducts,
        productsAllowed: task.input.productsAllowed,
      };
      const output = computeOffset(
        meta,
        task.input.tradeTimes,
        task.input.tradePrices,
        task.input.priceTimes,
        task.input.priceMids,
      );
      return { kind: 'offset', output };
    }
    case 'effRealized': {
      const meta = {
        tradeProducts: task.input.tradeProducts,
        priceProducts: task.input.priceProducts,
        horizonTimestamp: task.input.horizonTimestamp,
        productsAllowed: task.input.productsAllowed,
      };
      const output = computeEffRealized(
        meta,
        task.input.tradeTimes,
        task.input.tradePrices,
        task.input.priceTimes,
        task.input.priceMids,
      );
      return { kind: 'effRealized', output };
    }
    case 'corrMatrix': {
      const meta = {
        products: task.input.products,
        productsAllowed: task.input.productsAllowed,
        returnHorizon: task.input.returnHorizon,
      };
      const output = computeCorrMatrix(meta, task.input.times, task.input.mids);
      return { kind: 'corrMatrix', output };
    }
    case 'leadLag': {
      const meta = {
        products: task.input.products,
        productA: task.input.productA,
        productB: task.input.productB,
        maxLagSteps: task.input.maxLagSteps,
        stepTimestamp: task.input.stepTimestamp,
      };
      const output = computeLeadLag(meta, task.input.times, task.input.mids);
      return { kind: 'leadLag', output };
    }
    case 'pairSpread': {
      const meta = {
        products: task.input.products,
        productA: task.input.productA,
        productB: task.input.productB,
        zWindow: task.input.zWindow,
      };
      const output = computePairSpread(meta, task.input.times, task.input.mids);
      return { kind: 'pairSpread', output };
    }
    case 'obsBeta': {
      const meta = {
        obsColumns: task.input.obsColumns.map(c => ({ name: c.name, values: Array.from(c.values) })),
        priceProducts: task.input.priceProducts,
        lagTimestamp: task.input.lagTimestamp,
        productsAllowed: task.input.productsAllowed,
      };
      const output = computeObsBeta(meta, task.input.obsTimes, task.input.priceTimes, task.input.priceMids);
      return { kind: 'obsBeta', output };
    }
    case 'seasonality': {
      const meta = {
        products: task.input.products,
        dayPeriod: task.input.dayPeriod,
        buckets: task.input.buckets,
        productsAllowed: task.input.productsAllowed,
      };
      const output = computeSeasonality(
        meta,
        task.input.times,
        task.input.mids,
        task.input.bid1,
        task.input.ask1,
      );
      return { kind: 'seasonality', output };
    }
  }
}

self.addEventListener('message', async event => {
  const request = event.data as WorkerRequest;
  let response: WorkerResponse;
  try {
    await ensureReady();
    const result = runTask(request);
    response = { id: request.id, ok: true, result };
  } catch (err) {
    response = { id: request.id, ok: false, error: err instanceof Error ? err.message : String(err) };
  }
  (self as unknown as Worker).postMessage(response);
});
