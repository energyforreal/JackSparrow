# UI/UX Documentation

## Overview

This document describes the user interface design, component specifications, user interaction flows, and visual design guidelines for the **JackSparrow** dashboard.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [Design Principles](#design-principles)
- [Dashboard Layout](#dashboard-layout)
- [Technology Stack](#technology-stack)
- [Component Specifications](#component-specifications)
- [User Interaction Flows](#user-interaction-flows)
- [Visual Design Guidelines](#visual-design-guidelines)
- [Tailwind CSS Configuration](#tailwind-css-configuration)
- [shadcn/ui Integration](#shadcnui-integration)
- [Component Mapping](#component-mapping)
- [Usage Patterns](#usage-patterns)
- [Responsive Design](#responsive-design)
- [Accessibility Considerations](#accessibility-considerations)
- [Animation Guidelines](#animation-guidelines)
- [Error States](#error-states)
- [Related Documentation](#related-documentation)

---

## Design Principles

### Core Principles

1. **Clarity First**: Information should be clear and easy to understand
2. **Real-Time Awareness**: Users should always know the current state
3. **Transparency**: Show agent reasoning and decision-making process
4. **Actionable Insights**: Display information that helps users understand and control the agent
5. **Responsive Design**: Works on desktop, tablet, and mobile devices

---

## Dashboard Layout

### Overall Structure

```
┌─────────────────────────────────────────────────────────┐
│  Header: Logo, Title, Connection Status                   │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Agent Status │  │ Signal       │  │ Health       │  │
│  │              │  │ Indicator    │  │ Monitor      │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────┐  │
│  │ Portfolio Summary                                │  │
│  │ Total Value | Cash | Positions | PnL            │  │
│  └──────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │ Active Positions  │  │ Recent Trades            │  │
│  │                   │  │                          │  │
│  └──────────────────┘  └──────────────────────────┘  │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────┐  │
│  │ Performance Chart                                 │  │
│  │                                                   │  │
│  └──────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────┐  │
│  │ Reasoning Chain Viewer                           │  │
│  │                                                   │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## Technology Stack

The JackSparrow dashboard UI is built using modern web technologies:

- **Next.js 14+**: React framework with App Router
- **TypeScript**: Type-safe development
- **Tailwind CSS**: Utility-first CSS framework for styling
- **shadcn/ui**: High-quality component library built on Radix UI and Tailwind CSS
- **Radix UI**: Unstyled, accessible component primitives
- **Lucide React**: Icon library
- **react-hot-toast**: Lightweight trade-execution toasts (mounted from `app/providers.tsx`)

This combination provides:
- **Rapid Development**: Tailwind utilities enable fast styling without custom CSS
- **Accessibility**: shadcn/ui components are built on Radix UI primitives with ARIA support
- **Customization**: Components are copied into the project, allowing full customization
- **Type Safety**: TypeScript ensures type-safe component props and styling
- **Consistency**: Design system enforced through Tailwind configuration and shadcn components

---

## Component Specifications

### AgentStatus Component

**Purpose**: Display current agent state with visual indicators

**Visual Design**:
- Large status badge with color coding
- Icon representing current state
- Status text
- Last update timestamp
- Optional status message

**Color Scheme**:
- **MONITORING**: Green (#10B981) - Active monitoring
- **ANALYZING**: Blue (#3B82F6) - Processing signals
- **TRADING**: Orange (#F59E0B) - Active trade
- **DEGRADED**: Yellow (#FCD34D) - Reduced functionality
- **EMERGENCY_STOP**: Red (#EF4444) - Critical stop

**Layout**:
```
┌─────────────────────────────────────┐
│  👁️  MONITORING                    │
│  Monitoring Markets                 │
│  Last update: 10:30:15 AM           │
└─────────────────────────────────────┘
```

**States**:
- **MONITORING**: 👁️ "Monitoring Markets"
- **ANALYZING**: 🧠 "Analyzing Signals"
- **TRADING**: ⚡ "Active Trade"
- **DEGRADED**: ⚠️ "Degraded Performance"
- **EMERGENCY_STOP**: 🚨 "Emergency Stop"

---

### SignalIndicator Component

**Purpose**: Display current AI prediction signal

**Visual Design**:
- Large signal badge (BUY/SELL/HOLD)
- Confidence bar visualization
- Model consensus breakdown
- Expandable reasoning section

**Strong signals**: **STRONG_BUY** and **STRONG_SELL** use an additional **pulse** (`animate-ping`) ring so they stand out from regular BUY/SELL at a glance (main badge and per-model consensus rows).

**Signal Badge Colors**:
- **STRONG_BUY**: Dark Green (#059669)
- **BUY**: Green (#10B981)
- **HOLD**: Gray (#6B7280)
- **SELL**: Red (#EF4444)
- **STRONG_SELL**: Dark Red (#DC2626)

**Layout**:
```
┌─────────────────────────────────────┐
│  ┌─────────┐                       │
│  │   BUY    │  Confidence: 75%      │
│  └─────────┘                       │
│  ▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░  │
│                                     │
│  Model Consensus:                  │
│  • XGBoost: BUY (85%)              │
│  • LSTM: BUY (75%)                 │
│  • Transformer: BUY (70%)          │
│                                     │
│  [View Reasoning Chain →]           │
└─────────────────────────────────────┘
```

**Confidence Bar**:
- Visual progress bar
- Color-coded by confidence level
- Percentage display
- Smooth animations on updates

---

### PortfolioSummary Component

**Purpose**: Display portfolio overview with key metrics

**Visual Design**:
- Large total value display
- Breakdown cards (Cash, Positions, PnL)
- Color-coded PnL (green/red)
- Percentage changes
- Trend indicators

**Layout**:
```
┌─────────────────────────────────────────────────┐
│  Portfolio Value                                │
│  $100,500.00  ↗ +2.5%                           │
│                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Cash     │  │ Positions│  │ PnL      │    │
│  │ $95,000  │  │ $5,000   │  │ +$500    │    │
│  └──────────┘  └──────────┘  └──────────┘    │
└─────────────────────────────────────────────────┘
```

**Metrics Displayed**:
- Total Portfolio Value
- Cash Balance
- Positions Value
- Unrealized PnL
- Realized PnL
- Percentage Changes

---

### ActivePositions Component

**Purpose**: Display list of currently open positions

**Visual Design**:
- Table layout
- Color-coded PnL
- Entry vs current price comparison
- Position duration
- Real-time updates

**Layout**:
```
┌─────────────────────────────────────────────────┐
│  Active Positions                               │
├──────────┬──────┬─────────┬─────────┬──────────┤
│ Symbol   │ Qty  │ Entry   │ Current │ PnL     │
├──────────┼──────┼─────────┼─────────┼──────────┤
│ BTCUSD   │ 0.1  │ $49,000 │ $50,000 │ +$100   │
└──────────┴──────┴─────────┴─────────┴──────────┘
```

**Table Columns**:
- Symbol
- Quantity
- Entry Price
- Current Price
- Unrealized PnL (color-coded)
- Entry Time
- Duration

**Color Coding**:
- Positive PnL: Green (#10B981)
- Negative PnL: Red (#EF4444)
- Neutral: Gray (#6B7280)

---

### RecentTrades Component

**Purpose**: Display recent trade history

**Visual Design**:
- List/table layout
- Trade details
- PnL indicators
- Status badges
- Timestamps

**Layout**:
```
┌─────────────────────────────────────────────────┐
│  Recent Trades                                 │
├──────────┬──────┬──────┬──────┬──────┬────────┤
│ Time     │ Side │ Qty  │ Price│ PnL  │ Status │
├──────────┼──────┼──────┼──────┼──────┼────────┤
│ 10:30 AM │ BUY  │ 0.05 │ $50K │ +$25 │ Closed │
│ 10:00 AM │ SELL │ 0.1  │ $49K │ +$10 │ Closed │
└──────────┴──────┴──────┴──────┴──────┴────────┘
```

**Display Options**:
- Last 10 trades (default)
- Filterable by symbol
- Sortable by time/PnL
- Expandable for details

---

### PerformanceChart Component

**Purpose**: Visualize portfolio performance over time

**Visual Design**:
- Line chart
- Time period selector
- Interactive tooltips
- PnL overlay
- Responsive sizing

**Chart Features**:
- Portfolio value line
- PnL bars (optional)
- Time period selector (1d, 7d, 30d, all)
- Zoom functionality
- Hover tooltips

**Layout**:
```
┌─────────────────────────────────────────────────┐
│  Performance Chart                    [1d|7d|30d|All] │
│                                                 │
│      ┌─────────────────────────────┐           │
│      │                             │           │
│      │        ╱╲                   │           │
│      │      ╱    ╲                 │           │
│      │    ╱        ╲               │           │
│      │  ╱            ╲             │           │
│      └─────────────────────────────┘           │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

### HealthMonitor Component

**Purpose**: Display system health status

**Visual Design**:
- Overall health score
- Service status grid
- Latency indicators
- Degradation reasons
- Color-coded status

**Layout**:
```
┌─────────────────────────────────────────────────┐
│  System Health                          Score: 95% │
│                                                 │
│  ┌─────────────┬──────────┬─────────────────┐ │
│  │ Service     │ Status   │ Latency         │ │
│  ├─────────────┼──────────┼─────────────────┤ │
│  │ Database    │ ✓ Up     │ 5ms             │ │
│  │ Redis       │ ✓ Up     │ 2ms             │ │
│  │ Agent       │ ✓ Up     │ -               │ │
│  │ Delta API   │ ✓ Up     │ 150ms           │ │
│  └─────────────┴──────────┴─────────────────┘ │
└─────────────────────────────────────────────────┘
```

**Status Indicators**:
- ✓ Green: Up and healthy
- ⚠ Yellow: Degraded
- ✗ Red: Down

---

### ReasoningChainView Component

**Purpose**: Display agent's reasoning chain for transparency

**Visual Design**:
- Expandable step-by-step reasoning
- Confidence indicators
- Evidence badges
- Conclusion highlight
- Copy functionality

**Layout**:
```
┌─────────────────────────────────────────────────┐
│  Agent Reasoning Chain              Confidence: 75% │
│                                                 │
│  ▼ Step 1: Situational Assessment     85%      │
│    Market Regime: bull_trending...             │
│                                                 │
│  ▼ Step 2: Historical Context        80%      │
│    Found 5 similar situations...               │
│                                                 │
│  ▼ Step 3: Model Consensus           75%      │
│    Consensus Signal: BUY...                   │
│                                                 │
│  ┌───────────────────────────────────────────┐ │
│  │ Conclusion: After analyzing...           │ │
│  └───────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

**Step Display**:
- Step number and title
- Expandable thought process
- Confidence bar
- Evidence tags
- Collapsible sections

---

### LearningReport Component

**Purpose**: Display agent learning updates

**Visual Design**:
- Key lessons list
- Model weight changes
- Strategy adaptations
- Timestamp
- Visual change indicators

**Layout**:
```
┌─────────────────────────────────────────────────┐
│  Learning Report                    Updated: 10:30 AM │
│                                                 │
│  Key Lessons:                                  │
│  • Early entries in uptrends perform better    │
│  • Volume confirmation increases accuracy       │
│                                                 │
│  Model Weight Changes:                         │
│  • XGBoost: +0.05 (0.30 → 0.35)               │
│  • LSTM: -0.02 (0.25 → 0.23)                  │
│                                                 │
│  Strategy Adaptations:                         │
│  • Position size increased by 5%              │
└─────────────────────────────────────────────────┘
```

---

## User Interaction Flows

### Viewing Agent Status

1. User opens dashboard
2. AgentStatus component displays current state
3. WebSocket connection established
4. Real-time state updates received
5. Component updates automatically

**User Actions**:
- View current state
- See last update time
- Read status messages

---

### Requesting Prediction

1. User clicks "Get Prediction" button
2. API request sent to backend
3. Backend requests prediction from agent
4. Agent generates reasoning chain
5. Response displayed in SignalIndicator
6. ReasoningChainView updated

**User Actions**:
- Click prediction button
- View signal and confidence
- Expand reasoning chain
- Review model predictions

---

### Viewing Reasoning Chain

1. User clicks "View Reasoning Chain"
2. ReasoningChainView component expands
3. All 6 steps displayed
4. User can expand individual steps
5. Evidence and confidence shown

**User Actions**:
- Expand/collapse steps
- View detailed thoughts
- See evidence tags
- Copy reasoning chain
- Review conclusion

---

### Monitoring Portfolio

1. Dashboard loads portfolio data
2. PortfolioSummary displays overview
3. ActivePositions shows open positions
4. RecentTrades shows history
5. WebSocket updates in real-time

**User Actions**:
- View portfolio value
- Check positions
- Review trade history
- Monitor PnL changes

---

### Checking System Health

1. HealthMonitor component loads
2. Health check API called
3. Service statuses displayed
4. Health score calculated
5. Updates via WebSocket

**User Actions**:
- View overall health
- Check individual services
- See latency metrics
- Review degradation reasons

---

## Visual Design Guidelines

### Color Palette

**Primary Colors**:
- Primary Blue: `#3B82F6`
- Primary Green: `#10B981`
- Primary Red: `#EF4444`
- Primary Yellow: `#F59E0B`

**Neutral Colors**:
- Gray 50: `#F9FAFB`
- Gray 100: `#F3F4F6`
- Gray 200: `#E5E7EB`
- Gray 500: `#6B7280`
- Gray 900: `#111827`

**Status Colors**:
- Success: `#10B981`
- Warning: `#F59E0B`
- Error: `#EF4444`
- Info: `#3B82F6`

---

### Typography

**Font Families**:
- Headings: Inter, system-ui, sans-serif
- Body: system-ui, -apple-system, sans-serif
- Monospace: 'Courier New', monospace (for data)

**Font Sizes**:
- H1: 2.25rem (36px)
- H2: 1.875rem (30px)
- H3: 1.5rem (24px)
- Body: 1rem (16px)
- Small: 0.875rem (14px)

**Font Weights**:
- Light: 300
- Regular: 400
- Medium: 500
- Semibold: 600
- Bold: 700

---

### Spacing

**Spacing Scale**:
- xs: 0.25rem (4px)
- sm: 0.5rem (8px)
- md: 1rem (16px)
- lg: 1.5rem (24px)
- xl: 2rem (32px)
- 2xl: 3rem (48px)

**Component Spacing**:
- Card padding: 1.5rem
- Section margin: 2rem
- Element gap: 1rem

---

### Shadows and Borders

**Shadows**:
- Small: `0 1px 2px rgba(0,0,0,0.05)`
- Medium: `0 4px 6px rgba(0,0,0,0.1)`
- Large: `0 10px 15px rgba(0,0,0,0.1)`

**Borders**:
- Default: `1px solid #E5E7EB`
- Focus: `2px solid #3B82F6`
- Error: `1px solid #EF4444`

**Border Radius**:
- Small: 0.25rem (4px)
- Medium: 0.5rem (8px)
- Large: 0.75rem (12px)

---

## Tailwind CSS Configuration

### Setup and Installation

Tailwind CSS is installed and configured in the Next.js frontend. The configuration file is located at `frontend/tailwind.config.js`.

**Installation** (if setting up from scratch):

```bash
cd frontend
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

### Configuration File Structure

The `tailwind.config.js` file extends Tailwind's default theme with custom colors, spacing, and typography:

```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // Custom trading colors
        success: "#10B981",
        warning: "#F59E0B",
        error: "#EF4444",
        info: "#3B82F6",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["Courier New", "monospace"],
      },
      keyframes: {
        "accordion-down": {
          from: { height: 0 },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: 0 },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
```

### Custom Theme Configuration

**CSS Variables** (defined in `globals.css`):

The theme uses CSS variables for dynamic theming and dark mode support:

```css
@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222.2 84% 4.9%;
    --card: 0 0% 100%;
    --card-foreground: 222.2 84% 4.9%;
    --popover: 0 0% 100%;
    --popover-foreground: 222.2 84% 4.9%;
    --primary: 221.2 83.2% 53.3%;
    --primary-foreground: 210 40% 98%;
    --secondary: 210 40% 96.1%;
    --secondary-foreground: 222.2 47.4% 11.2%;
    --muted: 210 40% 96.1%;
    --muted-foreground: 215.4 16.3% 46.9%;
    --accent: 210 40% 96.1%;
    --accent-foreground: 222.2 47.4% 11.2%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 210 40% 98%;
    --border: 214.3 31.8% 91.4%;
    --input: 214.3 31.8% 91.4%;
    --ring: 221.2 83.2% 53.3%;
    --radius: 0.5rem;
  }

  .dark {
    --background: 222.2 84% 4.9%;
    --foreground: 210 40% 98%;
    --card: 222.2 84% 4.9%;
    --card-foreground: 210 40% 98%;
    --popover: 222.2 84% 4.9%;
    --popover-foreground: 210 40% 98%;
    --primary: 217.2 91.2% 59.8%;
    --primary-foreground: 222.2 47.4% 11.2%;
    --secondary: 217.2 32.6% 17.5%;
    --secondary-foreground: 210 40% 98%;
    --muted: 217.2 32.6% 17.5%;
    --muted-foreground: 215 20.2% 65.1%;
    --accent: 217.2 32.6% 17.5%;
    --accent-foreground: 210 40% 98%;
    --destructive: 0 62.8% 30.6%;
    --destructive-foreground: 210 40% 98%;
    --border: 217.2 32.6% 17.5%;
    --input: 217.2 32.6% 17.5%;
    --ring: 224.3 76.3% 94.1%;
  }
}
```

### Utility Class Patterns

**Common Patterns Used in Components**:

1. **Layout Utilities**:
   - `flex`, `grid` for layouts
   - `items-center`, `justify-between` for alignment
   - `gap-2`, `gap-4` for spacing

2. **Spacing Utilities**:
   - `p-3`, `px-4`, `py-2` for padding
   - `m-2`, `mx-auto`, `my-4` for margins
   - `space-x-2`, `space-y-4` for child spacing

3. **Color Utilities**:
   - `bg-background`, `text-foreground` for theme colors
   - `bg-emerald-500/10` for semi-transparent backgrounds
   - `text-emerald-400` for colored text
   - `border-emerald-500/20` for colored borders

4. **Responsive Utilities**:
   - `sm:`, `md:`, `lg:`, `xl:` prefixes for breakpoints
   - `md:grid-cols-2`, `lg:grid-cols-3` for responsive grids

5. **State Utilities**:
   - `hover:`, `focus:`, `active:` for interactive states
   - `disabled:opacity-50` for disabled states
   - `aria-[state]:` for ARIA-based styling

### Dark Mode Configuration

Dark mode is enabled using the `class` strategy:

```javascript
darkMode: ["class"]
```

Toggle dark mode by adding/removing the `dark` class on the root element:

```tsx
// Toggle dark mode
document.documentElement.classList.toggle('dark');
```

Components automatically adapt using CSS variables defined in the `:root` and `.dark` selectors.

---

## shadcn/ui Integration

### Overview

shadcn/ui is a collection of re-usable components built using Radix UI and Tailwind CSS. Unlike traditional component libraries, shadcn/ui components are **copied into your project**, giving you full control over the source code.

### Installation

**Initial Setup**:

```bash
cd frontend
npx shadcn-ui@latest init
```

This command will:
1. Create a `components.json` configuration file
2. Set up the required dependencies (Radix UI, class-variance-authority, clsx, tailwind-merge)
3. Configure the component directory structure

**Component Directory Structure**:

```
frontend/
├── components/
│   └── ui/              # shadcn/ui components
│       ├── badge.tsx
│       ├── button.tsx
│       ├── card.tsx
│       ├── table.tsx
│       ├── progress.tsx
│       └── ...
├── lib/
│   └── utils.ts        # cn() utility function
└── components.json      # shadcn configuration
```

### Configuration File (`components.json`)

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "default",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.js",
    "css": "app/globals.css",
    "baseColor": "slate",
    "cssVariables": true,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils"
  }
}
```

### Adding Components

Add shadcn/ui components as needed:

```bash
# Add a specific component
npx shadcn-ui@latest add button
npx shadcn-ui@latest add card
npx shadcn-ui@latest add table
npx shadcn-ui@latest add badge
npx shadcn-ui@latest add progress
npx shadcn-ui@latest add accordion
npx shadcn-ui@latest add dialog
npx shadcn-ui@latest add tabs
```

### Theme Customization

shadcn/ui components use CSS variables for theming, which are defined in your `globals.css` file. Customize colors by modifying the CSS variable values:

```css
:root {
  --primary: 221.2 83.2% 53.3%;  /* Customize primary color */
  --secondary: 210 40% 96.1%;     /* Customize secondary color */
  /* ... other variables */
}
```

### Component Customization

Since components are copied into your project, you can:

1. **Modify directly**: Edit component files in `components/ui/`
2. **Extend with variants**: Use `class-variance-authority` for variant-based styling
3. **Override styles**: Use Tailwind utilities to override default styles
4. **Add features**: Extend components with additional functionality

**Example - Custom Button Variant**:

```tsx
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline: "border border-input bg-background hover:bg-accent",
        // Custom trading variant
        trading: "bg-emerald-500 text-white hover:bg-emerald-600",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3",
        lg: "h-11 rounded-md px-8",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);
```

### Utility Function (`lib/utils.ts`)

The `cn()` function merges Tailwind classes and handles conditional classes:

```tsx
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

**Usage**:

```tsx
import { cn } from "@/lib/utils";

<div className={cn(
  "base-classes",
  condition && "conditional-classes",
  anotherCondition ? "class-a" : "class-b"
)} />
```

---

## Component Mapping

This section maps the documented UI components to their shadcn/ui component implementations.

### AgentStatus Component

**shadcn/ui Components Used**:
- `Badge` - Status indicator badge
- `Card` - Container for status information

**Implementation**:

```tsx
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function AgentStatus({ state, message, lastUpdate }: AgentStatusProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Agent Status</CardTitle>
      </CardHeader>
      <CardContent>
        <Badge variant="outline" className={getStateClasses(state)}>
          {getStateIcon(state)} {state}
        </Badge>
        {message && <p className="text-sm text-muted-foreground mt-2">{message}</p>}
        <p className="text-xs text-muted-foreground mt-1">Last update: {lastUpdate}</p>
      </CardContent>
    </Card>
  );
}
```

### SignalIndicator Component

**shadcn/ui Components Used**:
- `Badge` - Signal badge (BUY/SELL/HOLD)
- `Progress` - Confidence bar visualization
- `Card` - Container
- `Accordion` - Expandable reasoning section

**Implementation**:

```tsx
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

export function SignalIndicator({ signal, confidence, modelConsensus }: SignalIndicatorProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>AI Signal</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-4">
          <Badge className={getSignalBadgeClasses(signal)}>
            {signal}
          </Badge>
          <div className="flex-1">
            <div className="flex justify-between text-sm mb-1">
              <span>Confidence</span>
              <span>{confidence}%</span>
            </div>
            <Progress value={confidence} className="h-2" />
          </div>
        </div>
        <Accordion type="single" collapsible className="mt-4">
          <AccordionItem value="consensus">
            <AccordionTrigger>Model Consensus</AccordionTrigger>
            <AccordionContent>
              {/* Model consensus breakdown */}
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </CardContent>
    </Card>
  );
}
```

### PortfolioSummary Component

**shadcn/ui Components Used**:
- `Card` - Main container and metric cards
- `Badge` - Trend indicators

**Implementation**:

```tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown } from "lucide-react";

export function PortfolioSummary({ portfolio }: PortfolioSummaryProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Portfolio Value</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-bold">
          ${portfolio.totalValue.toLocaleString()}
          <Badge variant={portfolio.change >= 0 ? "default" : "destructive"} className="ml-2">
            {portfolio.change >= 0 ? <TrendingUp /> : <TrendingDown />}
            {Math.abs(portfolio.change)}%
          </Badge>
        </div>
        <div className="grid grid-cols-3 gap-4 mt-4">
          <Card>
            <CardContent className="pt-4">
              <div className="text-sm text-muted-foreground">Cash</div>
              <div className="text-xl font-semibold">${portfolio.cash.toLocaleString()}</div>
            </CardContent>
          </Card>
          {/* Similar cards for Positions and PnL */}
        </div>
      </CardContent>
    </Card>
  );
}
```

### ActivePositions Component

**shadcn/ui Components Used**:
- `Table` - Table layout for positions
- `Badge` - PnL indicators

**Implementation**:

```tsx
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ActivePositions({ positions }: ActivePositionsProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Active Positions</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Symbol</TableHead>
              <TableHead>Quantity</TableHead>
              <TableHead>Entry Price</TableHead>
              <TableHead>Current Price</TableHead>
              <TableHead>PnL</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {positions.map((position) => (
              <TableRow key={position.symbol}>
                <TableCell>{position.symbol}</TableCell>
                <TableCell>{position.quantity}</TableCell>
                <TableCell>${position.entryPrice.toLocaleString()}</TableCell>
                <TableCell>${position.currentPrice.toLocaleString()}</TableCell>
                <TableCell>
                  <Badge variant={position.pnl >= 0 ? "default" : "destructive"}>
                    {position.pnl >= 0 ? "+" : ""}${position.pnl.toLocaleString()}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
```

### RecentTrades Component

**shadcn/ui Components Used**:
- `Table` - Trade history table
- `Badge` - Status badges

**Implementation**: Similar to ActivePositions, using `Table` component with trade-specific columns.

### PerformanceChart Component

**shadcn/ui Components Used**:
- `Card` - Chart container
- `Tabs` - Time period selector

**Implementation**: Uses a charting library (e.g., Recharts) wrapped in shadcn/ui `Card` and `Tabs` components for period selection.

### HealthMonitor Component

**shadcn/ui Components Used**:
- `Card` - Container
- `Badge` - Status indicators
- `Progress` - Health score visualization

**Implementation**:

```tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { CheckCircle2, AlertCircle, XCircle } from "lucide-react";

export function HealthMonitor({ health }: HealthMonitorProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>System Health</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="mb-4">
          <div className="flex justify-between text-sm mb-1">
            <span>Overall Score</span>
            <span>{health.score}%</span>
          </div>
          <Progress value={health.score} className="h-2" />
        </div>
        <div className="space-y-2">
          {health.services.map((service) => (
            <div key={service.name} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {getStatusIcon(service.status)}
                <span>{service.name}</span>
              </div>
              <Badge variant={getStatusVariant(service.status)}>
                {service.status}
              </Badge>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
```

### ReasoningChainView Component

**shadcn/ui Components Used**:
- `Accordion` - Expandable step-by-step reasoning
- `Card` - Conclusion highlight
- `Progress` - Confidence indicators
- `Badge` - Evidence tags

**Implementation**: Uses `Accordion` for collapsible steps, `Card` for conclusion, and `Badge` components for evidence tags.

### LearningReport Component

**shadcn/ui Components Used**:
- `Card` - Container
- `Badge` - Change indicators

**Implementation**: Uses `Card` with structured content and `Badge` components to highlight changes.

---

## Usage Patterns

### Common Tailwind Patterns

**1. Conditional Styling with `cn()`**:

```tsx
import { cn } from "@/lib/utils";

<div className={cn(
  "base-classes",
  isActive && "active-classes",
  variant === "primary" ? "primary-classes" : "secondary-classes"
)} />
```

**2. Responsive Grid Layouts**:

```tsx
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
  {/* Cards */}
</div>
```

**3. Flexbox Patterns**:

```tsx
// Centered content
<div className="flex items-center justify-center h-full">
  {/* Content */}
</div>

// Space between
<div className="flex items-center justify-between">
  <span>Label</span>
  <Badge>Value</Badge>
</div>
```

**4. Color Variants**:

```tsx
// Using theme colors
<div className="bg-card text-card-foreground border border-border">
  {/* Content */}
</div>

// Using custom colors with opacity
<div className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
  {/* Content */}
</div>
```

### shadcn Component Customization

**1. Extending Button Component**:

```tsx
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

<Button 
  className={cn(
    "default-button-classes",
    "custom-additional-classes"
  )}
>
  Custom Button
</Button>
```

**2. Custom Card Variants**:

```tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

<Card className={cn("default-card", "border-emerald-500/20 bg-emerald-500/5")}>
  <CardHeader>
    <CardTitle>Custom Card</CardTitle>
  </CardHeader>
  <CardContent>
    {/* Content */}
  </CardContent>
</Card>
```

**3. Table with Custom Styling**:

```tsx
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

<Table>
  <TableHeader>
    <TableRow className="hover:bg-muted/50">
      <TableHead className="font-semibold">Column</TableHead>
    </TableRow>
  </TableHeader>
  <TableBody>
    <TableRow className="hover:bg-muted/30">
      <TableCell className="font-medium">Value</TableCell>
    </TableRow>
  </TableBody>
</Table>
```

### Best Practices

**1. Component Composition**:

Combine shadcn/ui components to build complex UI:

```tsx
<Card>
  <CardHeader>
    <CardTitle>Title</CardTitle>
  </CardHeader>
  <CardContent>
    <Table>
      {/* Table content */}
    </Table>
    <div className="mt-4 flex justify-end gap-2">
      <Button variant="outline">Cancel</Button>
      <Button>Confirm</Button>
    </div>
  </CardContent>
</Card>
```

**2. Consistent Spacing**:

Use Tailwind's spacing scale consistently:

```tsx
// Good: Consistent spacing
<div className="space-y-4">
  <Card className="p-4">...</Card>
  <Card className="p-4">...</Card>
</div>

// Avoid: Inconsistent spacing
<div>
  <Card className="p-3">...</Card>
  <Card className="p-6">...</Card>
</div>
```

**3. Accessibility First**:

Always include accessibility attributes:

```tsx
<Button
  aria-label="Close dialog"
  aria-describedby="dialog-description"
  onClick={handleClose}
>
  Close
</Button>
```

**4. Dark Mode Support**:

Use CSS variables for colors to ensure dark mode compatibility:

```tsx
// Good: Uses CSS variables
<div className="bg-background text-foreground border-border">
  {/* Content */}
</div>

// Avoid: Hard-coded colors (won't adapt to dark mode)
<div className="bg-white text-black border-gray-300">
  {/* Content */}
</div>
```

### Performance Considerations

**1. Class Merging**:

Always use `cn()` for conditional classes to avoid conflicts:

```tsx
// Good
<div className={cn("base", condition && "conditional")} />

// Avoid: Manual string concatenation
<div className={`base ${condition ? "conditional" : ""}`} />
```

**2. Component Reusability**:

Create reusable component variants:

```tsx
// components/ui/status-badge.tsx
export function StatusBadge({ status }: { status: "success" | "error" | "warning" }) {
  return (
    <Badge 
      variant={status === "success" ? "default" : status === "error" ? "destructive" : "secondary"}
      className={cn(
        "status-specific-classes",
        status === "success" && "bg-emerald-500",
        status === "error" && "bg-red-500"
      )}
    >
      {status}
    </Badge>
  );
}
```

---

## Responsive Design

### Breakpoints

- Mobile: < 640px
- Tablet: 640px - 1024px
- Desktop: > 1024px

### Mobile Layout

- Single column layout
- Stacked components
- Collapsible sections
- Touch-friendly buttons
- Simplified navigation

### Tablet Layout

- Two-column layout where appropriate
- Maintained component sizes
- Touch-friendly interactions

### Desktop Layout

- Multi-column layout
- Full component visibility
- Hover interactions
- Keyboard navigation

---

## Accessibility Considerations

### ARIA Labels

- All interactive elements have ARIA labels
- Status indicators use `aria-live` regions
- Charts include descriptive text
- Form inputs properly labeled

### Keyboard Navigation

- Tab order follows visual flow
- Focus indicators visible
- Keyboard shortcuts available
- Skip links for main content

### Screen Reader Support

- Semantic HTML elements
- Descriptive alt text for images
- Status announcements
- Error messages announced

**Accessible Component Example**:

```tsx
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface AgentStatusBadgeProps {
  state: string;
  message?: string;
}

export function AgentStatusBadge({ state, message }: AgentStatusBadgeProps) {
  const stateColors = {
    MONITORING: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    ANALYZING: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    TRADING: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    DEGRADED: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
    EMERGENCY_STOP: "bg-red-500/10 text-red-400 border-red-500/20",
  };

  return (
    <Badge
      variant="outline"
      className={cn(
        "flex items-center gap-2 px-3 py-2",
        stateColors[state as keyof typeof stateColors]
      )}
      role="status"
      aria-live="polite"
    >
      <span className="h-2 w-2 rounded-full bg-current" aria-hidden="true" />
      <span className="text-sm font-medium">{state}</span>
      <span className="sr-only">Agent state updated: {state}</span>
      {message && <span className="text-xs opacity-70">{message}</span>}
    </Badge>
  );
}
```

This example uses the shadcn/ui `Badge` component with Tailwind utility classes. The `cn()` utility function (from `lib/utils`) merges Tailwind classes conditionally. The component maintains accessibility with `role="status"` and screen reader support.

### Visual Accessibility

- High contrast mode support
- Color-blind friendly palette
- Text size scaling
- Focus indicators

---

## Animation Guidelines

### Transitions

- Smooth transitions for state changes
- Duration: 200-300ms
- Easing: ease-in-out

### Loading States

- Skeleton screens for content loading
- Spinner for API calls
- Progress indicators for long operations

### Real-Time Updates

- Subtle animations for value changes
- Color transitions for status changes
- Smooth scrolling for new items

---

## Error States

### Connection Errors

- Clear error message
- Retry button
- Connection status indicator
- Fallback to cached data

### API Errors

- Error message display
- Error code and details
- Suggested actions
- Support contact information

### Empty States

- Helpful empty state messages
- Guidance on next steps
- Visual indicators

**Dashboard (implemented)**:
- Portfolio, active positions, and recent trades use **dashed-border** empty panels with primary + secondary lines when data is loaded but absent.
- Recent trades avoids showing “no trades” during the initial portfolio/trades fetch by using a dedicated **`isLoading`** skeleton state.

### Loading states (skeletons)

- **Portfolio summary**, **positions table**, and **trades table** use **Tailwind `animate-pulse`** placeholders that mirror the final layout (not a generic single bar).
- Shown while WebSocket is not yet connected or portfolio loading flags are true; see [Frontend: Dashboard UX enhancements](07-frontend.md#dashboard-ux-enhancements).

### Trade feedback

- New executions surface as a **toast** (bottom-right) for both unified `data_update` / `trade` and legacy `trade_executed` messages, without changing server payloads.

---

## Related Documentation

- [Frontend Documentation](07-frontend.md) - Implementation details
- [Features Documentation](04-features.md) - Feature specifications
- [Architecture Documentation](01-architecture.md) - System design
- [Build Guide](11-build-guide.md) - Project setup and build instructions
- [Deployment Documentation](10-deployment.md) - Environment setup and deployment

### Operational Commands
- Command execution (`start`, `restart`, `audit`, `error`) is CLI-driven; no direct UI surface is provided.
- Make the command set discoverable via the documentation menu (links to [Build Guide](11-build-guide.md#project-commands) and [Deployment Documentation](10-deployment.md#operations--maintenance-commands)).
- Consider adding a status banner that reflects the result of the latest `audit` or `error` diagnostic if future UI enhancements are planned.

