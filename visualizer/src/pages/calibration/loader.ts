// HTTP client for the calibration endpoints.

import axios from 'axios';
import { CalibrationAsset, CalibrationParams, FvAndBook } from './types';

const ASSETS_URL  = '/__prosperity4mcbt__/calibration/assets';
const DATA_URL    = '/__prosperity4mcbt__/calibration/data';
const PARAMS_URL  = '/__prosperity4mcbt__/calibration/params';

export async function fetchAssets(): Promise<CalibrationAsset[]> {
  const res = await axios.get<{ assets: CalibrationAsset[] }>(ASSETS_URL);
  return res.data.assets;
}

export async function fetchData(asset: string): Promise<FvAndBook | null> {
  try {
    const res = await axios.get<FvAndBook>(DATA_URL, { params: { asset } });
    return res.data;
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 404) return null;
    throw err;
  }
}

export async function fetchParams(asset: string): Promise<CalibrationParams | null> {
  try {
    const res = await axios.get<CalibrationParams>(PARAMS_URL, { params: { asset } });
    return res.data;
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 404) return null;
    throw err;
  }
}

export async function writeParams(asset: string, params: CalibrationParams): Promise<void> {
  await axios.post(PARAMS_URL, params, { params: { asset } });
}
