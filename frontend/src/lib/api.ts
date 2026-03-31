/**
 * API client factory — creates an authenticated API client that injects
 * Bearer tokens, org context, and project context headers into every request.
 */

const BASE = '/api';

export type GetToken = () => Promise<string>;

export function createApiClient(getToken: GetToken, orgId: string, projectId: string = '') {
  async function headers(): Promise<Record<string, string>> {
    const h: Record<string, string> = {};
    const token = await getToken();
    if (token) h['Authorization'] = `Bearer ${token}`;
    if (orgId) h['X-Org-Id'] = orgId;
    if (projectId) h['X-Project-Id'] = projectId;
    return h;
  }

  async function parseResponse(res: Response) {
    const text = await res.text();
    try {
      const data = JSON.parse(text);
      if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
      return data;
    } catch (e) {
      if (!res.ok) throw new Error(text || `Request failed (${res.status})`);
      throw e;
    }
  }

  async function post(path: string, body: FormData | Record<string, unknown>) {
    const isForm = body instanceof FormData;
    const h = await headers();
    if (!isForm) h['Content-Type'] = 'application/json';
    const res = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: h,
      body: isForm ? body : JSON.stringify(body),
    });
    return parseResponse(res);
  }

  async function get(path: string) {
    const h = await headers();
    const res = await fetch(`${BASE}${path}`, { headers: h });
    return parseResponse(res);
  }

  async function del(path: string) {
    const h = await headers();
    const res = await fetch(`${BASE}${path}`, { method: 'DELETE', headers: h });
    return parseResponse(res);
  }

  // -- Me --
  const getMe = () => get('/me');

  // -- Schemas --
  const listSchemas = () => get('/schemas');
  const getSchema = (docType: string) => get(`/schemas/${docType}`);
  const saveSchema = (docType: string, schema: Record<string, unknown>) =>
    post(`/schemas/${docType}`, schema);

  // -- Extract --
  async function extractPdf(file: File, docType: string, customSchema?: string) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('doc_type', docType);
    if (customSchema) fd.append('custom_schema', customSchema);
    return post('/extract', fd);
  }

  // -- Ground Truth --
  const listGroundTruth = () => get('/ground-truth');

  async function uploadGroundTruth(pdf: File, truthJson: File, docType: string) {
    const fd = new FormData();
    fd.append('pdf', pdf);
    fd.append('truth_json', truthJson);
    fd.append('doc_type', docType);
    return post('/ground-truth', fd);
  }

  async function saveAsGroundTruth(sourceFile: string, docType: string, correctedJson: string) {
    const fd = new FormData();
    fd.append('source_file', sourceFile);
    fd.append('doc_type', docType);
    fd.append('corrected_json', correctedJson);
    return post('/save-as-ground-truth', fd);
  }

  const cacheGroundTruth = () => post('/cache', new FormData());

  // -- Evaluate --
  const runEvaluation = () => post('/evaluate', new FormData());

  // -- SQL --
  async function generateSql(
    extractedJson: string, tableName: string, dialect: string,
    schemaName: string, includeDdl: boolean,
  ) {
    const fd = new FormData();
    fd.append('extracted_json', extractedJson);
    fd.append('table_name', tableName);
    fd.append('dialect', dialect);
    fd.append('schema_name', schemaName);
    fd.append('include_ddl', String(includeDdl));
    return post('/generate-sql', fd);
  }

  async function executeSql(sql: string, connectionString: string) {
    const fd = new FormData();
    fd.append('sql', sql);
    fd.append('connection_string', connectionString);
    return post('/execute-sql', fd);
  }

  async function testConnection(connectionString: string) {
    const fd = new FormData();
    fd.append('connection_string', connectionString);
    return post('/test-connection', fd);
  }

  // -- Schema Generation --
  async function generateSchema(description: string, docTypeKey: string) {
    const fd = new FormData();
    fd.append('description', description);
    fd.append('doc_type_key', docTypeKey);
    return post('/generate-schema', fd);
  }

  // -- Organizations --
  async function createOrg(name: string) {
    const fd = new FormData();
    fd.append('name', name);
    return post('/orgs', fd);
  }

  const listMyOrgs = () => get('/me/orgs');
  const getDbStatus = (orgId: string) => get(`/orgs/${orgId}/db-status`);

  async function requestJoinOrg(targetOrgId: string) {
    const fd = new FormData();
    fd.append('org_id', targetOrgId);
    return post('/orgs/join', fd);
  }

  const listJoinRequests = () => get('/orgs/requests');

  async function resolveJoinRequest(requestId: string, approve: boolean) {
    const fd = new FormData();
    fd.append('approve', String(approve));
    return post(`/orgs/requests/${requestId}/resolve`, fd);
  }

  // -- Projects --
  const listProjects = () => get('/projects');

  async function createProject(name: string, slug: string, description: string = '') {
    const fd = new FormData();
    fd.append('name', name);
    fd.append('slug', slug);
    fd.append('description', description);
    return post('/projects', fd);
  }

  const getProject = (projectId: string) => get(`/projects/${projectId}`);

  async function addProjectMember(projectId: string, userSub: string, userEmail: string = '') {
    const fd = new FormData();
    fd.append('user_sub', userSub);
    fd.append('user_email', userEmail);
    return post(`/projects/${projectId}/members`, fd);
  }

  const removeProjectMember = (projectId: string, userSub: string) =>
    del(`/projects/${projectId}/members/${userSub}`);

  async function deleteProject(projectId: string, confirmName: string) {
    const h = await headers();
    h['X-Confirm-Name'] = confirmName;
    const res = await fetch(`${BASE}/projects/${projectId}`, { method: 'DELETE', headers: h });
    return parseResponse(res);
  }

  // -- Documents --
  async function uploadDocument(projectId: string, pdfFile: File, groundTruthFile?: File) {
    const fd = new FormData();
    fd.append('project_id', projectId);
    fd.append('file', pdfFile);
    if (groundTruthFile) fd.append('ground_truth', groundTruthFile);
    return post('/documents/upload', fd);
  }

  async function saveCorrections(projectId: string, sourceFile: string, docType: string, correctedJson: Record<string, unknown>) {
    const fd = new FormData();
    fd.append('project_id', projectId);
    fd.append('source_file', sourceFile);
    fd.append('doc_type', docType);
    fd.append('corrected_json', JSON.stringify(correctedJson));
    return post('/documents/correct', fd);
  }

  const getProjectSchema = (projectId: string) => get(`/projects/${projectId}/schema`);

  async function startBackgroundOptimization(projectId: string) {
    const fd = new FormData();
    fd.append('project_id', projectId);
    return post('/wiggum/start-background', fd);
  }

  const getExtractionStatus = (projectId: string) => get(`/projects/${projectId}/extraction-status`);

  // -- Wiggum Loop --
  async function startWiggum(cycles: number, experiments: number, model: string) {
    const fd = new FormData();
    fd.append('cycles', String(cycles));
    fd.append('experiments', String(experiments));
    fd.append('model', model);
    return post('/wiggum/start', fd);
  }

  const getWiggumStatus = (projectId?: string) =>
    get(projectId ? `/wiggum/status?project_id=${projectId}` : '/wiggum/status');
  const getWiggumHistory = () => get('/wiggum/history');

  // -- Knowledge Base (RAG) --
  const kbStats = () => get('/kb/stats');
  const kbSchema = () => get('/kb/schema');

  async function kbIndex(docType: string, extractedJson: string, sourceFile: string = '') {
    const fd = new FormData();
    fd.append('doc_type', docType);
    fd.append('extracted_json', extractedJson);
    fd.append('source_file', sourceFile);
    return post('/kb/index', fd);
  }

  async function kbQuery(question: string) {
    return post('/kb/query', (() => { const fd = new FormData(); fd.append('question', question); return fd; })());
  }

  return {
    getMe,
    listSchemas, getSchema, saveSchema,
    extractPdf,
    listGroundTruth, uploadGroundTruth, saveAsGroundTruth, cacheGroundTruth,
    runEvaluation,
    generateSql, executeSql, testConnection,
    generateSchema,
    createOrg, listMyOrgs, getDbStatus, requestJoinOrg, listJoinRequests, resolveJoinRequest,
    listProjects, createProject, getProject, addProjectMember, removeProjectMember, deleteProject,
    uploadDocument, saveCorrections, getProjectSchema, startBackgroundOptimization, getExtractionStatus,
    startWiggum, getWiggumStatus, getWiggumHistory,
    kbStats, kbSchema, kbIndex, kbQuery,
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
