import { apiClient } from './client';

export interface Email {
    id: string;
    email_date: string;
    email_from: string;
    email_to: string;
    email_cc: string;
    email_subject: string;
    body_text?: string;
    content?: string;
    meta?: {
        content?: string;
        attachments?: unknown[];
    };
    attachments?: unknown[];
}

export interface FetchEmailsParams {
    projectId?: string;
    caseId?: string;
}

export const fetchEmails = async (params: FetchEmailsParams): Promise<Email[]> => {
    const queryParams = new URLSearchParams();
    if (params.projectId) queryParams.append('project_id', params.projectId);
    if (params.caseId) queryParams.append('case_id', params.caseId);

    const response = await apiClient.get<{ emails: Email[] }>(`/correspondence/emails?${queryParams.toString()}`);
    return response.data.emails;
};

export const fetchAgGridLicense = async (): Promise<string | null> => {
    try {
        const response = await apiClient.get<{ license: string }>('/config/ag-grid-license');
        return response.data.license;
    } catch (error) {
        console.warn('Failed to fetch AG Grid license', error);
        return null;
    }
}

