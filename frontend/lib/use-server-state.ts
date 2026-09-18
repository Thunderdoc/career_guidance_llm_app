"use client";

import { useEffect, useState } from "react";
import { getServerState, onServerState, type ServerState } from "./api";

/** Subscribe to the API client's transport state (idle | waking | ready | unreachable). */
export function useServerState(): ServerState {
  const [state, setState] = useState<ServerState>(getServerState);
  useEffect(() => onServerState(setState), []);
  return state;
}
