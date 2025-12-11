# Timestamp Formatting Implementation

**Date**: 2025-01-27  
**Status**: Implemented

## Overview

This document describes the timestamp formatting implementation that ensures consistent UTC → IST (Indian Standard Time) conversion across the frontend application. The implementation addresses issues with timestamp parsing and display synchronization.

## Problem Statement

Previously, timestamps from backend WebSocket messages were not being correctly parsed as UTC, causing incorrect IST display times (approximately 5.5 hours offset). The issue was caused by:

1. Backend sending timestamps without timezone suffix: `"2025-01-27T12:33:19.976865"`
2. JavaScript `Date` constructor interpreting these as local time instead of UTC
3. Double conversion when displaying in IST, resulting in incorrect times

## Solution Architecture

### Core Components

1. **`normalizeDate()` Function** (`frontend/utils/formatters.ts`)
   - Normalizes timestamp strings to Date objects
   - Detects timezone indicators (Z, +00:00, +0000)
   - Appends 'Z' to timestamps without timezone (treats as UTC)
   - Handles edge cases (whitespace, multiple timezone formats)

2. **`formatClockTime()` Function** (`frontend/utils/formatters.ts`)
   - Formats timestamps to match system clock format
   - Converts UTC → IST using `toLocaleTimeString`
   - Displays as `HH:mm:ss am/pm` format

3. **Enhanced Hook Logic** (`frontend/hooks/useAgent.ts`)
   - Uses `normalizeDate()` for all timestamp parsing
   - Includes error handling for invalid timestamps
   - Debug logging in development mode

4. **Component Updates**
   - `DataFreshnessIndicator`: Uses `normalizeDate()` for age calculation
   - `AgentStatus`: Receives normalized Date objects
   - `SignalIndicator`: Displays normalized timestamps
   - `TradingDecision`: Displays normalized timestamps

## Implementation Details

### Timestamp Normalization Flow

```
Backend sends: "2025-01-27T12:33:19.976865" (no timezone)
    ↓
normalizeDate() detects no timezone
    ↓
Appends 'Z': "2025-01-27T12:33:19.976865Z"
    ↓
new Date() parses as UTC
    ↓
formatClockTime() converts UTC → IST
    ↓
Display: "12:43:02 pm" (IST, matching system clock)
```

### normalizeDate Function

```typescript
export function normalizeDate(date: Date | string): Date {
  if (typeof date === 'string') {
    const trimmedDate = date.trim()
    const hasExplicitTimezone =
      trimmedDate.endsWith('Z') || 
      /[+-]\d{2}:\d{2}$/.test(trimmedDate) ||
      /[+-]\d{4}$/.test(trimmedDate)

    const isoString = hasExplicitTimezone ? trimmedDate : `${trimmedDate}Z`
    return new Date(isoString)
  }
  return date
}
```

**Key Features**:
- Trims whitespace from input strings
- Detects multiple timezone formats (Z, +00:00, +0000)
- Appends 'Z' when timezone is missing (ensures UTC parsing)
- Returns Date object for consistent handling

### formatClockTime Function

```typescript
export function formatClockTime(date: Date | string | null | undefined): string {
  if (!date || !isValidDate(date)) {
    return '--:--:--'
  }
  const d = normalizeDate(date)
  return d.toLocaleTimeString(IST_LOCALE, {
    timeZone: IST_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}
```

**Key Features**:
- Uses `normalizeDate()` to ensure UTC parsing
- Converts to IST using `toLocaleTimeString` with `timeZone: 'Asia/Kolkata'`
- Formats as `HH:mm:ss am/pm` matching system clock
- Handles null/undefined inputs gracefully

### Data Freshness Color Coding

Updated thresholds for more granular freshness indication:

- **< 30 seconds**: Green (very fresh)
- **30-60 seconds**: Light green (fresh)
- **1-2 minutes**: Yellow (recent)
- **2-5 minutes**: Amber (moderate)
- **5-15 minutes**: Orange (stale)
- **>= 15 minutes**: Red (very stale)

Both text color and dot indicator use these thresholds for consistency.

## Timestamp Sources

### Backend Format

Backend sends timestamps using Python's `datetime.utcnow().isoformat()`:
- Format: `YYYY-MM-DDTHH:mm:ss.sss` (no timezone suffix)
- Example: `"2025-01-27T12:33:19.976865"`
- This is standard ISO 8601 format without timezone (assumed UTC)

### Frontend Normalization

Frontend normalizes timestamps before parsing:
- Detects missing timezone
- Appends 'Z' to ensure UTC interpretation
- Parses using JavaScript `Date` constructor
- Converts to IST for display

### Display Format

All timestamps are displayed in IST:
- Format: `HH:mm:ss am/pm`
- Timezone: Asia/Kolkata (IST, UTC+5:30)
- Matches system clock format for consistency

## Components Using Timestamps

### 1. AgentStatus Component

**Location**: `frontend/app/components/AgentStatus.tsx`

**Timestamp Source**: `lastUpdate` from `useAgent` hook
- Updated when `agent_state` WebSocket messages arrive
- Uses `normalizeDate()` for parsing
- Displays via `DataFreshnessIndicator`

### 2. SignalIndicator Component

**Location**: `frontend/app/components/SignalIndicator.tsx`

**Timestamp Source**: `signal.timestamp` from WebSocket messages
- Updated when `signal_update` messages arrive
- Uses `normalizeDate()` via `formatClockTime()`
- Displays via `DataFreshnessIndicator`

### 3. TradingDecision Component

**Location**: `frontend/app/components/TradingDecision.tsx`

**Timestamp Source**: `signal.timestamp` from WebSocket messages
- Updated when `signal_update` messages arrive
- Uses `normalizeDate()` via `formatClockTime()`
- Displays as "Decision time" via `DataFreshnessIndicator`

## Debug Logging

Comprehensive debug logging is available in development mode:

### normalizeDate Logging

```typescript
console.log('[normalizeDate] Timestamp normalization:', {
  raw_input: date,
  has_explicit_timezone: hasExplicitTimezone,
  normalized_iso_string: isoString,
  parsed_date: parsedDate,
  parsed_utc_iso: parsedDate.toISOString(),
  parsed_local_string: parsedDate.toString(),
  is_valid: !isNaN(parsedDate.getTime()),
  current_time: new Date().toISOString(),
  current_time_local: new Date().toString()
})
```

### formatClockTime Logging

```typescript
console.log('[formatClockTime] Time formatting:', {
  input: date,
  normalized_date: d,
  normalized_utc_iso: d.toISOString(),
  formatted_ist_time: formatted,
  current_time_utc: new Date().toISOString(),
  current_time_ist: /* formatted current IST time */
})
```

### useAgent Hook Logging

Enhanced logging for signal updates:
- Raw timestamp from WebSocket
- Parsed Date object
- UTC ISO string
- Time difference from current time
- Error details if parsing fails

## Testing

### Manual Testing Steps

1. **Start the application** and open browser console (development mode)
2. **Monitor WebSocket messages** for timestamp values
3. **Verify normalization logs** show 'Z' being appended
4. **Check display times** match system clock (IST)
5. **Verify color coding** changes based on timestamp age

### Expected Behavior

- Timestamps without timezone should have 'Z' appended in logs
- Parsed timestamps should show correct UTC ISO strings
- Display times should match system clock (IST)
- Color coding should reflect actual data age

## Related Documentation

- [Frontend Documentation](../07-frontend.md) - Timestamp normalization section
- [Backend Documentation](../06-backend.md) - Timestamp format section
- [Signal Freshness Validation](./signal-freshness-validation.md) - Timestamp flow analysis

## Files Modified

1. `frontend/utils/formatters.ts`
   - Enhanced `normalizeDate()` with improved timezone detection
   - Added `formatClockTime()` function
   - Added debug logging

2. `frontend/hooks/useAgent.ts`
   - Updated timestamp parsing to use `normalizeDate()`
   - Enhanced error handling
   - Added debug logging

3. `frontend/app/components/DataFreshnessIndicator.tsx`
   - Updated `getFreshnessDotColor()` to use `normalizeDate()`
   - Added debug logging
   - Updated freshness thresholds

4. `frontend/app/components/AgentStatus.tsx`
   - Updated prop type to accept `Date | null`
   - Uses normalized timestamps

5. `frontend/app/components/SignalIndicator.tsx`
   - Uses `signal.timestamp` with normalization

6. `frontend/app/components/TradingDecision.tsx`
   - Uses `signal.timestamp` with normalization

## Success Criteria

✅ Timestamps without timezone are treated as UTC (Z appended)  
✅ All timestamps display correct IST time  
✅ Timestamps match system clock format and timezone  
✅ No more ~5.5 hour offset errors  
✅ Color coding reflects actual data freshness  
✅ Debug logging provides visibility into timestamp processing

## Future Enhancements

- Consider adding timezone preference configuration
- Add unit tests for timestamp normalization edge cases
- Consider caching normalized Date objects for performance
- Add timestamp validation warnings for very old data

