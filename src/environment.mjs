// Keep existing deployments working while publishing only the OCE_* interface.
export function normalizeEnvironment(environment) {
  const result = {...environment};
  for (const [key,value] of Object.entries(environment)) {
    if (!key.startsWith('REPONERVE_')) continue;
    const current = 'OCE_' + key.slice('REPONERVE_'.length);
    if (!Object.hasOwn(environment,current)) result[current] = value;
  }
  return result;
}
