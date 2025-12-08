import { apiClient } from './client';

export interface Attachment {
    id?: string;
    filename?: string;
    name?: string;
    content_type?: string;
    contentType?: string;
    file_size?: number;
    size?: number;
    s3_key?: string;
    s3_bucket?: string;
    is_inline?: boolean;
    is_embedded?: boolean;
    content_id?: string;
}

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
        attachments?: Attachment[];
    };
    attachments?: Attachment[];
}

export interface FetchEmailsParams {
    projectId?: string;
    caseId?: string;
}

// Helper function to check if an attachment is an embedded/inline image (should be excluded)
export const isEmbeddedImage = (att: Attachment): boolean => {
    // Trust is_inline or is_embedded flag from backend
    if (att.is_inline === true || att.is_embedded === true) return true;
    
    const filename = (att.filename || att.name || '').toLowerCase();
    const contentType = (att.content_type || att.contentType || '').toLowerCase();
    const fileSize = att.file_size || att.size || 0;
    
    // Common tracking/spacer images
    const trackingFiles = ['blank.gif', 'spacer.gif', 'pixel.gif', '1x1.gif', 'oledata.mso'];
    if (trackingFiles.includes(filename)) return true;
    
    // CID prefixed files (content-id inline images)
    if (filename.startsWith('cid:') || filename.startsWith('cid_')) return true;
    
    // Pattern: image001.png, image002.jpg, etc (Outlook inline)
    if (/^image\d{3}\.(png|jpg|jpeg|gif|bmp)$/.test(filename)) return true;
    
    // Pattern: img_001.png, img001.jpg, etc
    if (/^img_?\d+\.(png|jpg|jpeg|gif|bmp)$/.test(filename)) return true;
    
    // Small embedded images (signatures, logos, icons)
    if (contentType.includes('image')) {
        // Very small images are likely embedded icons/logos
        if (fileSize && fileSize < 20000) return true;
        
        // Check for signature/logo keywords
        const excludedKeywords = ['signature', 'logo', 'banner', 'header', 'footer', 'badge', 'icon'];
        if (excludedKeywords.some(kw => filename.includes(kw))) return true;
    }
    
    return false;
};

// Helper to get real (non-embedded) attachments from an email
export const getRealAttachments = (email: Email): Attachment[] => {
    const rawAttachments = email.attachments || email.meta?.attachments || [];
    if (!rawAttachments || !Array.isArray(rawAttachments)) return [];
    return rawAttachments.filter(att => !isEmbeddedImage(att));
};

// Helper to check if email has real attachments (excludes embedded images)
export const hasRealAttachments = (email: Email): boolean => {
    return getRealAttachments(email).length > 0;
};

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
