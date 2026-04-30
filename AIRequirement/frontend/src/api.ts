export interface Idea {
  id: string;
  content: string;
  status: "pending" | "researching" | "writing" | "completed" | "failed";
  created_at: string;
  updated_at: string;
}

export interface Document {
  id: string;
  idea_id: string;
  title: string;
  content: string;
  research: Record<string, unknown> | null;
  created_at: string;
}

export interface IdeaListResponse {
  ideas: Idea[];
  total: number;
}

export interface DocumentListResponse {
  documents: Document[];
  total: number;
}

const BASE_URL = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  return response.json();
}

export async function createIdea(content: string): Promise<Idea> {
  return request<Idea>("/ideas", {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export async function listIdeas(): Promise<IdeaListResponse> {
  return request<IdeaListResponse>("/ideas");
}

export async function getIdea(id: string): Promise<Idea> {
  return request<Idea>(`/ideas/${id}`);
}

export async function getDocumentForIdea(ideaId: string): Promise<Document> {
  return request<Document>(`/ideas/${ideaId}/document`);
}

export async function listDocuments(): Promise<DocumentListResponse> {
  return request<DocumentListResponse>("/documents");
}

export async function getDocument(id: string): Promise<Document> {
  return request<Document>(`/documents/${id}`);
}

export async function regenerateIdea(
  ideaId: string,
  rerunInstruction?: string,
): Promise<Idea> {
  return request<Idea>(`/ideas/${ideaId}/regenerate`, {
    method: "POST",
    body: JSON.stringify({ rerun_instruction: rerunInstruction || null }),
  });
}
