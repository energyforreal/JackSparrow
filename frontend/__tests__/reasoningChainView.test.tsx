import { render, screen } from '@testing-library/react'
import { ReasoningChainView } from '@/app/components/ReasoningChainView'

describe('ReasoningChainView', () => {
  it('shows path economics when only threshold is present', () => {
    render(
      <ReasoningChainView
        reasoningChain={[]}
        threshold={0.00125}
      />
    )

    expect(screen.queryByText(/No rationale available yet/i)).not.toBeInTheDocument()
    expect(screen.getByText('Path economics')).toBeInTheDocument()
    expect(screen.getByText(/Threshold:/)).toBeInTheDocument()
  })

  it('accepts legacy v43Threshold prop alias', () => {
    render(
      <ReasoningChainView
        reasoningChain={[]}
        v43Threshold={0.00125}
      />
    )
    expect(screen.getByText('Path economics')).toBeInTheDocument()
  })

  it('shows gate reject without reasoning steps', () => {
    render(
      <ReasoningChainView
        reasoningChain={[]}
        gateReject="path_edge_below_threshold"
      />
    )

    expect(screen.getByText(/Gate reject:/)).toBeInTheDocument()
    expect(screen.getByText('path_edge_below_threshold')).toBeInTheDocument()
  })

  it('renders multi-timeframe stance table', () => {
    render(
      <ReasoningChainView
        reasoningChain={[]}
        multiTfPredictions={{
          tf_15m: {
            local_signal: 'BUY',
            long_edge: 0.01,
            short_edge: -0.01,
            size_scale: 0.7,
            confidence: 0.62,
            resolution: '15m',
          },
          tf_5m: {
            local_signal: 'HOLD',
            path_edge: 0.001,
            size_scale: 0,
            confidence: 0.3,
            resolution: '5m',
          },
        }}
      />
    )
    expect(screen.getByText('Multi-timeframe stances')).toBeInTheDocument()
    expect(screen.getByText('15m')).toBeInTheDocument()
    expect(screen.getByText('BUY')).toBeInTheDocument()
  })

  it('shows empty state when no steps or economics fields', () => {
    render(<ReasoningChainView reasoningChain={[]} />)

    expect(screen.getByText(/No rationale available yet/i)).toBeInTheDocument()
  })
})
