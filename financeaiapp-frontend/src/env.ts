/**
 * Environment-aware configuration.
 *
 * Dev mode: Vite serves from localhost and proxies `/api` → local backend.
 * Prod mode: Built bundle uses Cognito Identity Pool + SigV4 to call AgentCore.
 */

export const isDev = import.meta.env.DEV;

export const appPassword = (import.meta.env.VITE_APP_PASSWORD ?? "") as string;

export const awsRegion = (import.meta.env.VITE_AWS_REGION ?? "us-east-1") as string;

export const identityPoolId = (import.meta.env.VITE_IDENTITY_POOL_ID ?? "") as string;

export const agentCoreRuntimeArn = (import.meta.env.VITE_AGENTCORE_RUNTIME_ARN ?? "") as string;

export function assertProdConfig(): void {
  if (isDev) return;
  if (!identityPoolId) throw new Error("VITE_IDENTITY_POOL_ID is required in production");
  if (!agentCoreRuntimeArn)
    throw new Error("VITE_AGENTCORE_RUNTIME_ARN is required in production");
}
