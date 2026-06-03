import { render, screen } from '@testing-library/react'
import { ReasoningChainView } from '@/app/components/ReasoningChainView'

describe('ReasoningChainView', () => {
  it('shows decision economics when only threshold is present', () => {
    render(
      <ReasoningChainView
        reasoningChain={[]}
        v43Threshold={0.00125}
      />
    )

    expect(screen.queryByText(/No rationale available yet/i)).not.toBeInTheDocument()
    expect(screen.getByText('Decision economics')).toBeInTheDocument()
    expect(screen.getByText(/Threshold:/)).toBeInTheDocument()
  })

  it('shows gate reject without reasoning steps', () => {
    render(
      <ReasoningChainView
        reasoningChain={[]}
        v43GateReject="expected_return_below_threshold"
      />
    )

    expect(screen.getByText(/Gate reject:/)).toBeInTheDocument()
    expect(screen.getByText('expected_return_below_threshold')).toBeInTheDocument()
  })

  it('shows empty state when no steps or economics fields', () => {
    render(<ReasoningChainView reasoningChain={[]} />)

    expect(screen.getByText(/No rationale available yet/i)).toBeInTheDocument()
  })
})
