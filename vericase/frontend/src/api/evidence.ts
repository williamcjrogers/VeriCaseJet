/**
 * Evidence Repository API Client
 * API calls for the evidence management system
 */

import { apiClient } from './client';

// ============================================================================
// TYPES
// ============================================================================

export interface EvidenceItem {
    id: string;
    filename: string;
    file_type?: string;
    mime_type?: string;
    file_size?: number;
    file_hash: string;
    evidence_type?: string;
    document_category?: string;
    document_date?: string;
    title?: string;
    author?: string;
    description?: string;
    page_count?: number;
    extracted_text?: string;
    extracted_parties?: Array<{ name: string; role?: string; confidence?: number }>;
    extracted_dates?: Array<{ date: string; context?: string }>;
    extracted_amounts?: Array<{ amount: number; currency: string }>;
    extracted_references?: Array<{ reference: string; type: string }>;
    auto_tags: string[];
    manual_tags: string[];
    processing_status: string;
    source_type?: string;
    source_path?: string;
    is_duplicate: boolean;
    is_starred: boolean;
    is_privileged: boolean;
    is_confidential: boolean;
    is_reviewed: boolean;
    notes?: string;
    case_id?: string;
    project_id?: string;
    collection_id?: string;
    correspondence_links?: CorrespondenceLink[];
    relations?: EvidenceRelation[];
    download_url?: string;
    created_at: string;
    updated_at?: string;
}

export interface EvidenceItemSummary {
    id: string;
    filename: string;
    file_type?: string;
    file_size?: number;
    evidence_type?: string;
    document_category?: string;
    document_date?: string;
    title?: string;
    processing_status: string;
    is_starred: boolean;
    is_reviewed: boolean;
    has_correspondence: boolean;
    correspondence_count: number;
    auto_tags: string[];
    manual_tags: string[];
    case_id?: string;
    project_id?: string;
    created_at: string;
}

export interface EvidenceListResponse {
    total: number;
    items: EvidenceItemSummary[];
    page: number;
    page_size: number;
}

export interface EvidenceCollection {
    id: string;
    name: string;
    description?: string;
    collection_type: string;
    parent_id?: string;
    item_count: number;
    is_system: boolean;
    color?: string;
    icon?: string;
    case_id?: string;
    project_id?: string;
}

export interface CorrespondenceLink {
    id: string;
    link_type: string;
    link_confidence?: number;
    link_method?: string;
    is_auto_linked: boolean;
    is_verified: boolean;
    context_snippet?: string;
    page_reference?: string;
    created_at?: string;
    email?: {
        id: string;
        subject?: string;
        sender_email?: string;
        sender_name?: string;
        date_sent?: string;
        has_attachments?: boolean;
    };
    external_correspondence?: {
        type?: string;
        reference?: string;
        date?: string;
        from?: string;
        to?: string;
        subject?: string;
    };
}

export interface EvidenceRelation {
    id: string;
    relation_type: string;
    direction: 'incoming' | 'outgoing';
    is_verified: boolean;
    related_item?: {
        id: string;
        filename: string;
        title?: string;
    };
}

export interface EvidenceStats {
    total: number;
    unassigned: number;
    with_correspondence: number;
    recent_uploads: number;
    by_type: Record<string, number>;
    by_status: Record<string, number>;
}

export interface EvidenceTypes {
    evidence_types: string[];
    document_categories: string[];
    link_types: string[];
    relation_types: string[];
}

export interface UploadInitResponse {
    evidence_id: string;
    upload_url: string;
    s3_bucket: string;
    s3_key: string;
}

export interface EvidenceListFilters {
    page?: number;
    page_size?: number;
    search?: string;
    evidence_type?: string;
    document_category?: string;
    date_from?: string;
    date_to?: string;
    tags?: string;
    has_correspondence?: boolean;
    is_starred?: boolean;
    is_reviewed?: boolean;
    unassigned?: boolean;
    case_id?: string;
    project_id?: string;
    collection_id?: string;
    processing_status?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
}

// ============================================================================
// EVIDENCE ITEM API
// ============================================================================

/**
 * Initialize evidence upload - get presigned URL
 */
export async function initEvidenceUpload(
    filename: string,
    fileSize: number,
    contentType?: string,
    caseId?: string,
    projectId?: string,
    collectionId?: string,
    tags?: string[]
): Promise<UploadInitResponse> {
    const response = await apiClient.post('/evidence/upload/init', {
        filename,
        file_size: fileSize,
        content_type: contentType,
        case_id: caseId,
        project_id: projectId,
        collection_id: collectionId,
        tags
    });
    return response.data;
}

/**
 * Complete evidence upload after file is uploaded to S3
 */
export async function completeEvidenceUpload(
    filename: string,
    s3Key: string,
    fileSize: number,
    fileHash: string,
    mimeType?: string,
    caseId?: string,
    projectId?: string,
    collectionId?: string,
    evidenceType?: string,
    title?: string,
    description?: string,
    documentDate?: string,
    tags?: string[]
): Promise<{ id: string; is_duplicate: boolean; duplicate_of_id?: string; message: string }> {
    const response = await apiClient.post('/evidence/upload/complete', {
        filename,
        s3_key: s3Key,
        file_size: fileSize,
        file_hash: fileHash,
        mime_type: mimeType,
        case_id: caseId,
        project_id: projectId,
        collection_id: collectionId,
        evidence_type: evidenceType,
        title,
        description,
        document_date: documentDate,
        tags
    });
    return response.data;
}

/**
 * Direct upload evidence file
 */
export async function uploadEvidenceDirect(
    file: File,
    caseId?: string,
    projectId?: string,
    collectionId?: string,
    evidenceType?: string,
    tags?: string[]
): Promise<{ id: string; is_duplicate: boolean; message: string }> {
    const formData = new FormData();
    formData.append('file', file);
    if (caseId) formData.append('case_id', caseId);
    if (projectId) formData.append('project_id', projectId);
    if (collectionId) formData.append('collection_id', collectionId);
    if (evidenceType) formData.append('evidence_type', evidenceType);
    if (tags) formData.append('tags', tags.join(','));

    const response = await apiClient.post('/evidence/upload/direct', formData, {
        headers: {
            'Content-Type': 'multipart/form-data'
        }
    });
    return response.data;
}

/**
 * List evidence items with filtering
 */
export async function listEvidence(filters: EvidenceListFilters = {}): Promise<EvidenceListResponse> {
    const params = new URLSearchParams();
    
    Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            params.append(key, String(value));
        }
    });

    const response = await apiClient.get(`/evidence/items?${params.toString()}`);
    return response.data;
}

/**
 * Get evidence item detail
 */
export async function getEvidenceDetail(evidenceId: string): Promise<EvidenceItem> {
    const response = await apiClient.get(`/evidence/items/${evidenceId}`);
    return response.data;
}

/**
 * Update evidence item
 */
export async function updateEvidence(
    evidenceId: string,
    updates: Partial<{
        title: string;
        description: string;
        evidence_type: string;
        document_category: string;
        document_date: string;
        manual_tags: string[];
        notes: string;
        is_starred: boolean;
        is_privileged: boolean;
        is_confidential: boolean;
        case_id: string;
        project_id: string;
        collection_id: string;
    }>
): Promise<{ id: string; message: string }> {
    const response = await apiClient.patch(`/evidence/items/${evidenceId}`, updates);
    return response.data;
}

/**
 * Delete evidence item
 */
export async function deleteEvidence(evidenceId: string): Promise<{ message: string }> {
    const response = await apiClient.delete(`/evidence/items/${evidenceId}`);
    return response.data;
}

/**
 * Assign evidence to case/project
 */
export async function assignEvidence(
    evidenceId: string,
    caseId?: string,
    projectId?: string
): Promise<{ id: string; case_id?: string; project_id?: string; message: string }> {
    const response = await apiClient.post(`/evidence/items/${evidenceId}/assign`, {
        case_id: caseId,
        project_id: projectId
    });
    return response.data;
}

/**
 * Toggle star status
 */
export async function toggleEvidenceStar(evidenceId: string): Promise<{ id: string; is_starred: boolean }> {
    const response = await apiClient.post(`/evidence/items/${evidenceId}/star`);
    return response.data;
}

// ============================================================================
// CORRESPONDENCE LINKS API
// ============================================================================

/**
 * Get correspondence links for evidence item
 */
export async function getEvidenceCorrespondence(
    evidenceId: string
): Promise<{ evidence_id: string; links: CorrespondenceLink[]; total: number }> {
    const response = await apiClient.get(`/evidence/items/${evidenceId}/correspondence`);
    return response.data;
}

/**
 * Link evidence to email
 */
export async function linkEvidenceToEmail(
    evidenceId: string,
    emailMessageId?: string,
    linkType: string = 'related',
    correspondenceType?: string,
    correspondenceReference?: string,
    correspondenceDate?: string,
    correspondenceFrom?: string,
    correspondenceTo?: string,
    correspondenceSubject?: string,
    contextSnippet?: string
): Promise<{ id: string; message: string }> {
    const response = await apiClient.post(`/evidence/items/${evidenceId}/link-email`, {
        email_message_id: emailMessageId,
        link_type: linkType,
        correspondence_type: correspondenceType,
        correspondence_reference: correspondenceReference,
        correspondence_date: correspondenceDate,
        correspondence_from: correspondenceFrom,
        correspondence_to: correspondenceTo,
        correspondence_subject: correspondenceSubject,
        context_snippet: contextSnippet
    });
    return response.data;
}

/**
 * Delete correspondence link
 */
export async function deleteCorrespondenceLink(linkId: string): Promise<{ message: string }> {
    const response = await apiClient.delete(`/evidence/correspondence-links/${linkId}`);
    return response.data;
}

// ============================================================================
// COLLECTIONS API
// ============================================================================

/**
 * List evidence collections
 */
export async function listCollections(
    includeSystem: boolean = true,
    caseId?: string,
    projectId?: string
): Promise<EvidenceCollection[]> {
    const params = new URLSearchParams();
    params.append('include_system', String(includeSystem));
    if (caseId) params.append('case_id', caseId);
    if (projectId) params.append('project_id', projectId);

    const response = await apiClient.get(`/evidence/collections?${params.toString()}`);
    return response.data;
}

/**
 * Create collection
 */
export async function createCollection(
    name: string,
    description?: string,
    parentId?: string,
    caseId?: string,
    projectId?: string,
    color?: string,
    icon?: string,
    filterRules?: Record<string, unknown>
): Promise<{ id: string; name: string; message: string }> {
    const response = await apiClient.post('/evidence/collections', {
        name,
        description,
        parent_id: parentId,
        case_id: caseId,
        project_id: projectId,
        color,
        icon,
        filter_rules: filterRules
    });
    return response.data;
}

/**
 * Update collection
 */
export async function updateCollection(
    collectionId: string,
    updates: Partial<{
        name: string;
        description: string;
        color: string;
        icon: string;
        filter_rules: Record<string, unknown>;
    }>
): Promise<{ id: string; message: string }> {
    const response = await apiClient.patch(`/evidence/collections/${collectionId}`, updates);
    return response.data;
}

/**
 * Delete collection
 */
export async function deleteCollection(collectionId: string): Promise<{ message: string }> {
    const response = await apiClient.delete(`/evidence/collections/${collectionId}`);
    return response.data;
}

/**
 * Add evidence to collection
 */
export async function addToCollection(
    collectionId: string,
    evidenceId: string
): Promise<{ message: string }> {
    const response = await apiClient.post(`/evidence/collections/${collectionId}/items/${evidenceId}`);
    return response.data;
}

/**
 * Remove evidence from collection
 */
export async function removeFromCollection(
    collectionId: string,
    evidenceId: string
): Promise<{ message: string }> {
    const response = await apiClient.delete(`/evidence/collections/${collectionId}/items/${evidenceId}`);
    return response.data;
}

// ============================================================================
// STATISTICS & REFERENCE DATA API
// ============================================================================

/**
 * Get evidence statistics
 */
export async function getEvidenceStats(
    caseId?: string,
    projectId?: string
): Promise<EvidenceStats> {
    const params = new URLSearchParams();
    if (caseId) params.append('case_id', caseId);
    if (projectId) params.append('project_id', projectId);

    const response = await apiClient.get(`/evidence/stats?${params.toString()}`);
    return response.data;
}

/**
 * Get evidence types reference data
 */
export async function getEvidenceTypes(): Promise<EvidenceTypes> {
    const response = await apiClient.get('/evidence/types');
    return response.data;
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Calculate SHA-256 hash of file
 */
export async function calculateFileHash(file: File): Promise<string> {
    const buffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Upload file with presigned URL
 */
export async function uploadToPresignedUrl(
    uploadUrl: string,
    file: File,
    onProgress?: (percent: number) => void
): Promise<void> {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        
        xhr.upload.addEventListener('progress', (event) => {
            if (event.lengthComputable && onProgress) {
                const percent = Math.round((event.loaded / event.total) * 100);
                onProgress(percent);
            }
        });

        xhr.addEventListener('load', () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                resolve();
            } else {
                reject(new Error(`Upload failed with status ${xhr.status}`));
            }
        });

        xhr.addEventListener('error', () => {
            reject(new Error('Upload failed'));
        });

        xhr.open('PUT', uploadUrl);
        xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
        xhr.send(file);
    });
}

/**
 * Full upload flow: init -> upload to S3 -> complete
 */
export async function uploadEvidence(
    file: File,
    options: {
        caseId?: string;
        projectId?: string;
        collectionId?: string;
        evidenceType?: string;
        title?: string;
        description?: string;
        documentDate?: string;
        tags?: string[];
        onProgress?: (percent: number) => void;
    } = {}
): Promise<{ id: string; is_duplicate: boolean; message: string }> {
    // 1. Calculate file hash
    const fileHash = await calculateFileHash(file);
    
    // 2. Initialize upload
    const initResponse = await initEvidenceUpload(
        file.name,
        file.size,
        file.type,
        options.caseId,
        options.projectId,
        options.collectionId,
        options.tags
    );
    
    // 3. Upload to S3
    await uploadToPresignedUrl(initResponse.upload_url, file, options.onProgress);
    
    // 4. Complete upload
    const completeResponse = await completeEvidenceUpload(
        file.name,
        initResponse.s3_key,
        file.size,
        fileHash,
        file.type,
        options.caseId,
        options.projectId,
        options.collectionId,
        options.evidenceType,
        options.title,
        options.description,
        options.documentDate,
        options.tags
    );
    
    return completeResponse;
}

/**
 * Format file size for display
 */
export function formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Get file icon based on type
 */
export function getFileIcon(fileType: string): string {
    const iconMap: Record<string, string> = {
        pdf: 'file-pdf',
        doc: 'file-word',
        docx: 'file-word',
        xls: 'file-excel',
        xlsx: 'file-excel',
        ppt: 'file-powerpoint',
        pptx: 'file-powerpoint',
        jpg: 'file-image',
        jpeg: 'file-image',
        png: 'file-image',
        gif: 'file-image',
        dwg: 'drafting-compass',
        dxf: 'drafting-compass',
        zip: 'file-archive',
        rar: 'file-archive',
        msg: 'envelope',
        eml: 'envelope',
    };
    return iconMap[fileType?.toLowerCase()] || 'file';
}

/**
 * Get evidence type display name
 */
export function getEvidenceTypeLabel(type: string): string {
    const labels: Record<string, string> = {
        contract: 'Contract',
        variation: 'Variation',
        drawing: 'Drawing',
        specification: 'Specification',
        programme: 'Programme',
        invoice: 'Invoice',
        payment_certificate: 'Payment Certificate',
        meeting_minutes: 'Meeting Minutes',
        site_instruction: 'Site Instruction',
        rfi: 'RFI',
        notice: 'Notice',
        letter: 'Letter',
        email: 'Email',
        photo: 'Photo',
        expert_report: 'Expert Report',
        claim: 'Claim',
        eot_notice: 'EOT Notice',
        delay_notice: 'Delay Notice',
        progress_report: 'Progress Report',
        quality_record: 'Quality Record',
        other: 'Other'
    };
    return labels[type] || type;
}

