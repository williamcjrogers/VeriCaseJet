import React, { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { timelineApi, TimelineEvent } from '../api/timeline';

export const TimelineView: React.FC = () => {
    const [searchParams] = useSearchParams();
    const caseId = searchParams.get('caseId') || 'dca0d854-1655-4498-97f3-399b47a4d65f'; // Default for dev

    const [events, setEvents] = useState<TimelineEvent[]>([]);
    const [viewMode, setViewMode] = useState<'timeline' | 'list'>('timeline');
    const [loading, setLoading] = useState(false);
    const [filterType, setFilterType] = useState<string>('all');

    useEffect(() => {
        loadData();
    }, [caseId]);

    const loadData = async () => {
        setLoading(true);
        try {
            const data = await timelineApi.getFullTimeline(caseId, {
                include_emails: true,
                include_programme: true
            });
            setEvents(data.events);
        } catch (error) {
            console.error('Failed to load timeline', error);
        } finally {
            setLoading(false);
        }
    };

    const filteredEvents = useMemo(() => {
        if (filterType === 'all') return events;
        return events.filter(e => e.type === filterType);
    }, [events, filterType]);

    const getEventColor = (type: string) => {
        switch(type) {
            case 'delay_event': return '#e74c3c'; // Red
            case 'milestone': return '#f1c40f'; // Yellow
            case 'email': return '#3498db'; // Blue
            case 'chronology_item': return '#9b59b6'; // Purple
            case 'activity': return '#2ecc71'; // Green
            default: return '#95a5a6'; // Gray
        }
    };

    return (
        <div className="timeline-view-container" style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
            <div className="header" style={{
                background: 'white', padding: '1rem 1.5rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                borderBottom: '1px solid #e2e8f0'
            }}>
                <h1 style={{ fontSize: '1.5rem', margin: 0 }}>Project Timeline</h1>
                <div style={{ display: 'flex', gap: '10px' }}>
                    <select
                        value={filterType}
                        onChange={(e) => setFilterType(e.target.value)}
                        style={{ padding: '0.5rem', borderRadius: '0.5rem', border: '1px solid #ddd' }}
                    >
                        <option value="all">All Types</option>
                        <option value="delay_event">Delays</option>
                        <option value="milestone">Milestones</option>
                        <option value="email">Correspondence</option>
                        <option value="chronology_item">Manual Items</option>
                    </select>

                    <div style={{ display: 'flex', border: '1px solid #ddd', borderRadius: '0.5rem', overflow: 'hidden' }}>
                        <button
                            onClick={() => setViewMode('timeline')}
                            style={{
                                padding: '0.5rem 1rem',
                                background: viewMode === 'timeline' ? '#17B5A3' : 'white',
                                color: viewMode === 'timeline' ? 'white' : 'black',
                                border: 'none',
                                borderRadius: 0,
                                cursor: 'pointer'
                            }}
                        >
                            Timeline
                        </button>
                        <button
                            onClick={() => setViewMode('list')}
                            style={{
                                padding: '0.5rem 1rem',
                                background: viewMode === 'list' ? '#17B5A3' : 'white',
                                color: viewMode === 'list' ? 'white' : 'black',
                                border: 'none',
                                borderRadius: 0,
                                cursor: 'pointer'
                            }}
                        >
                            List
                        </button>
                    </div>
                </div>
            </div>

            <div className="content-area" style={{ flex: 1, overflow: 'auto', padding: '20px', backgroundColor: '#f5f5f5' }}>
                {loading ? (
                    <div>Loading...</div>
                ) : viewMode === 'list' ? (
                    // List View
                    <div className="event-list" style={{ maxWidth: '800px', margin: '0 auto' }}>
                        {filteredEvents.map(event => (
                            <div key={event.id} style={{
                                backgroundColor: 'white',
                                padding: '15px',
                                marginBottom: '10px',
                                borderRadius: '8px',
                                borderLeft: `5px solid ${getEventColor(event.type)}`,
                                boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
                            }}>
                                <div style={{ fontSize: '0.85em', color: '#666' }}>
                                    {new Date(event.date).toLocaleDateString()} • {event.type.replace('_', ' ').toUpperCase()}
                                </div>
                                <div style={{ fontWeight: 'bold', fontSize: '1.1em', margin: '5px 0' }}>
                                    {event.title}
                                </div>
                                {event.description && (
                                    <div style={{ color: '#444' }}>{event.description}</div>
                                )}
                                {event.metadata && (
                                    <div style={{ marginTop: '10px', fontSize: '0.8em', color: '#888' }}>
                                        <pre>{JSON.stringify(event.metadata, null, 2)}</pre>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                ) : (
                    // Timeline View (Simple Horizontal)
                    <div className="timeline-visual" style={{ position: 'relative', minHeight: '400px', padding: '20px 0' }}>
                        <div style={{
                            position: 'absolute',
                            left: '50px',
                            top: 0,
                            bottom: 0,
                            width: '2px',
                            backgroundColor: '#ddd'
                        }}></div>

                        {filteredEvents.map((event) => (
                            <div key={event.id} style={{
                                display: 'flex',
                                alignItems: 'flex-start',
                                marginBottom: '20px',
                                position: 'relative'
                            }}>
                                <div style={{
                                    width: '100px',
                                    textAlign: 'right',
                                    paddingRight: '20px',
                                    fontSize: '0.9em',
                                    fontWeight: 'bold',
                                    color: '#555'
                                }}>
                                    {new Date(event.date).toLocaleDateString()}
                                </div>

                                <div style={{
                                    width: '12px',
                                    height: '12px',
                                    borderRadius: '50%',
                                    backgroundColor: getEventColor(event.type),
                                    position: 'absolute',
                                    left: '45px',
                                    top: '5px',
                                    zIndex: 1
                                }}></div>

                                <div style={{
                                    flex: 1,
                                    backgroundColor: 'white',
                                    padding: '10px 15px',
                                    borderRadius: '6px',
                                    border: '1px solid #eee',
                                    marginLeft: '20px'
                                }}>
                                    <div style={{ fontWeight: 'bold', color: getEventColor(event.type) }}>
                                        {event.title}
                                    </div>
                                    <div style={{ fontSize: '0.9em', marginTop: '5px' }}>
                                        {event.description}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};
