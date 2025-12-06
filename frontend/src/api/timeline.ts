import { apiClient } from './client';

export interface TimelineEvent {
    id: string;
    date: string; // ISO string
    type: 'chronology_item' | 'delay_event' | 'milestone' | 'critical_activity' | 'email' | 'manual';
    title: string;
    description?: string;
    source_id: string;
    metadata?: Record<string, any>;
}

export interface TimelineResponse {
    events: TimelineEvent[];
    total: number;
}

export interface ChronologyItem {
    id: string;
    event_date: string;
    title: string;
    description?: string;
    event_type: string;
    evidence_ids?: string[];
    parties_involved?: string[];
    claim_id?: string;
}

export interface ImportRequest {
    source_type: 'programme' | 'delay_event' | 'email';
    source_id?: string;
    date_range_start?: string;
    date_range_end?: string;
}

export const timelineApi = {
    // Get aggregated timeline (Programme + Delays + Emails + Chronology)
    getFullTimeline: async (caseId: string, params?: {
        start_date?: string;
        end_date?: string;
        include_emails?: boolean;
        include_programme?: boolean;
    }) => {
        const response = await apiClient.get<TimelineResponse>(`/cases/${caseId}/timeline`, { params });
        return response.data;
    },

    // Get manual chronology items
    getChronologyItems: async (caseId: string) => {
        const response = await apiClient.get<ChronologyItem[]>(`/cases/${caseId}/chronology`);
        return response.data;
    },

    // Create manual item
    createChronologyItem: async (caseId: string, item: Omit<ChronologyItem, 'id'>) => {
        const response = await apiClient.post(`/cases/${caseId}/chronology`, item);
        return response.data;
    },

    // Delete manual item
    deleteChronologyItem: async (caseId: string, itemId: string) => {
        const response = await apiClient.delete(`/cases/${caseId}/chronology/${itemId}`);
        return response.data;
    },

    // Import/Pin items to chronology
    importItems: async (caseId: string, request: ImportRequest) => {
        const response = await apiClient.post(`/cases/${caseId}/chronology/import`, request);
        return response.data;
    }
};
