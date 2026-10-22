
import ky, { HTTPError, type KyInstance, type KyRequest, type KyResponse } from 'ky';

// Types explicites pour les méthodes HTTP et les types de réponse
type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
type ResponseFormat = 'json' | 'blob' | 'stream';

// Configuration des URLs de base via variables d'environnement uniquement
const apiBaseUrls = {
  production: import.meta.env.VITE_API_URL_PROD,
  development: import.meta.env.VITE_API_URL,
  websocketDev: import.meta.env.VITE_WEBSOCKET_DEV,
  websocketProd: import.meta.env.VITE_WEBSOCKET_PROD,
};
// Interface pour une erreur enrichie
export interface CustomHttpError extends Error {
  status?: number;
  message: string;
}
type TargetApi = keyof typeof apiBaseUrls;

// Interface pour les options de chaque requête HTTP
export interface HttpRequestOptions {
  method: HttpMethod;
  endpoint: string;
  payload?: object | FormData | null;
  queryParams?: Record<string, string> | string | URLSearchParams | null;
  responseFormat?: ResponseFormat;
  targetApi?: TargetApi;
}

// Variable globale pour suivre l'API actuelle, exportée pour modification directe
let currentTargetApi: TargetApi = 'development';

// Instance globale de ky pour les requêtes HTTP
let httpClient: KyInstance;

// Hooks configurés pour toutes les requêtes
const requestHooks: Object = {

  beforeError: [
    async (error: HTTPError) => {
      const { response } = error;
      if (response) {
        try {
          const errorData = await response.json() as { message?: string, detail?: string };
          const customError = new Error(errorData.message || errorData.detail || 'Une erreur est survenue') as CustomHttpError;
          customError.status = response.status;
          return customError;
        } catch {
          const customError = new Error('Une erreur est survenue') as CustomHttpError;
          customError.status = response.status;
          return customError;
        }
      }
      return error;
    },
  ],

  afterResponse: [
    (_request: KyRequest, _options: any, _response: KyResponse) => { },
  ],
};

// Vérifie que toutes les URLs sont définies
function validateApiBaseUrls(): void {
  const missingKeys = Object.entries(apiBaseUrls)
    .filter(([, value]) => !value)
    .map(([key]) => key);
  if (missingKeys.length > 0) {
    console.warn(`Variables d'environnement manquantes pour : ${missingKeys.join(', ')}`);
  }
}

// Initialise l'instance HTTP une seule fois avec l'API actuelle
function initializeHttpClient(): void {
  if (!httpClient) {
    validateApiBaseUrls(); // Vérifie avant l'initialisation
    httpClient = ky.extend({
      //prefixUrl: apiBaseUrls[currentTargetApi],
      timeout: 30000, // 30 secondes
      retry: {
        limit: 2,
        statusCodes: [408, 413, 429, 500, 502, 503, 504],
      },
      hooks: requestHooks,
      credentials: 'include', // Important pour envoyer les cookies avec chaque requête
    });
  }
}

// Met à jour la base URL si l'API cible change
function updateClientBaseUrl(targetApi: TargetApi): void {
  const newBaseUrl = apiBaseUrls[targetApi];
  if (!newBaseUrl) {
    throw new Error(`URL non définie pour targetApi: ${targetApi}`);
  }
  httpClient = httpClient.extend({
    prefixUrl: newBaseUrl,
  });
}

// Exécute une requête HTTP avec l'API cible spécifiée ou actuelle
export async function handleHttpRequest<T = any>({
  method,
  endpoint,
  payload = null,
  queryParams = null,
  responseFormat = 'json',
  targetApi = currentTargetApi,
}: HttpRequestOptions): Promise<T> {
  initializeHttpClient();

  if (targetApi !== currentTargetApi) {
    updateClientBaseUrl(targetApi);
  }

  const requestMethod = method.toLowerCase() as Lowercase<HttpMethod>;
  const requestConfig = {
    searchParams: queryParams ?? undefined,
    ...(payload instanceof FormData ? { body: payload } : payload ? { json: payload } : {}),
  };
  try {
    if (responseFormat === 'stream') {
      return await httpClient[requestMethod](endpoint, requestConfig) as unknown as T;
    }
    return responseFormat === 'blob'
      ? (await httpClient[requestMethod](endpoint, requestConfig).blob()) as unknown as T
      : (await httpClient[requestMethod](endpoint, requestConfig).json<T>());
  } catch (error) {
    console.error(`Erreur lors de la requête ${method} sur ${endpoint}:`, error);
    throw error;
  }
}

// Export du client HTTP pour utilisation directe
export { httpClient }; 