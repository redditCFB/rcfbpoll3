(function () {
    'use strict';

    const container = document.getElementById('analysis-beeswarm');
    if (!container || typeof d3 === 'undefined') return;

    const results = JSON.parse(document.getElementById('analysis-beeswarm-data').textContent);
    const logoTemplate = container.dataset.logoUrlTemplate;
    const markerSize = 36;
    const markerGap = 4;
    const markerDiameter = markerSize + markerGap;
    const axisHeight = 42;
    const horizontalPadding = 12;

    results.forEach(result => {
        result.logo_url = logoTemplate.replace('{handle}', result.team_handle);
    });

    function fixedXBeeswarm(nodes) {
        nodes.sort((a, b) => a.x - b.x || a.rank - b.rank);
        nodes.forEach((node, index) => {
            const candidates = [0];

            for (let previousIndex = 0; previousIndex < index; previousIndex += 1) {
                const previous = nodes[previousIndex];
                const dx = Math.abs(node.x - previous.x);
                if (dx < markerDiameter) {
                    const dy = Math.sqrt(markerDiameter ** 2 - dx ** 2);
                    candidates.push(previous.y + dy, previous.y - dy);
                    candidates.push(previous.y + markerDiameter, previous.y - markerDiameter);
                }
            }

            candidates.sort((a, b) => Math.abs(a) - Math.abs(b) || a - b);
            node.y = candidates.find(candidate => nodes
                .slice(0, index)
                .every(previous => {
                    const dx = node.x - previous.x;
                    const dy = candidate - previous.y;
                    const epsilon = 1e-7;
                    return Math.hypot(dx, dy) >= markerDiameter - epsilon;
                }));
        });
        return nodes;
    }

    function render() {
        const width = Math.max(container.clientWidth, 1);
        const margin = { top: 8, right: horizontalPadding, bottom: axisHeight, left: horizontalPadding };
        const x = d3.scaleLinear().domain([0, 25]).range([
            margin.left + markerSize / 2,
            width - margin.right - markerSize / 2,
        ]).clamp(true);
        const nodes = fixedXBeeswarm(results.map(result => ({
            ...result,
            x: x(result.points_per_voter),
        })));
        const minY = d3.min(nodes, node => node.y) || 0;
        const maxY = d3.max(nodes, node => node.y) || 0;
        const plotTop = margin.top + markerSize / 2;
        const swarmHeight = maxY - minY;
        const height = Math.max(150, plotTop + swarmHeight + markerSize / 2 + axisHeight);
        const axisY = height - margin.bottom;

        d3.select(container).selectAll('.analysis-beeswarm-chart').remove();
        const chart = d3.select(container).append('div')
            .attr('class', 'analysis-beeswarm-chart');
        const svg = chart.append('svg')
            .attr('viewBox', '0 0 ' + width + ' ' + height)
            .attr('role', 'img')
            .attr('aria-labelledby', 'beeswarm-heading');
        const axis = d3.axisBottom(x).tickValues([0, 5, 10, 15, 20, 25]);
        svg.append('g').attr('transform', 'translate(0,' + axisY + ')').call(axis);
        svg.append('text').attr('x', width / 2).attr('y', height - 4)
            .attr('text-anchor', 'middle').text('Points per voter (PPV)');

        const tooltip = chart.append('div')
            .attr('class', 'analysis-beeswarm-tooltip')
            .attr('role', 'tooltip')
            .style('display', 'none');

        function positionTooltip(element, pointerEvent, node) {
            const chartBounds = chart.node().getBoundingClientRect();
            const elementBounds = element.getBoundingClientRect();
            const hasPointer = pointerEvent && pointerEvent.type !== 'focus' &&
                Number.isFinite(pointerEvent.clientX) && Number.isFinite(pointerEvent.clientY);
            const left = hasPointer
                ? pointerEvent.clientX - chartBounds.left + 8
                : elementBounds.left - chartBounds.left + markerSize / 2;
            const top = hasPointer
                ? pointerEvent.clientY - chartBounds.top - 8
                : elementBounds.top - chartBounds.top - 8;
            tooltip.text('Rank: #' + node.rank + '\nTeam: ' + node.team_name +
                '\nPPV: ' + Number(node.points_per_voter).toFixed(2))
                .style('display', 'block')
                .style('left', left + 'px')
                .style('top', top + 'px');
        }
        function showTooltip(event, node) {
            positionTooltip(this, event, node);
        }
        function hideTooltip() {
            tooltip.style('display', 'none');
        }

        svg.selectAll('image').data(nodes).join('image')
            .attr('class', 'team-marker')
            .attr('x', node => node.x - markerSize / 2)
            .attr('y', node => plotTop + node.y - minY - markerSize / 2)
            .attr('width', markerSize)
            .attr('height', markerSize)
            .attr('preserveAspectRatio', 'xMidYMid meet')
            .attr('href', node => node.logo_url)
            .attr('opacity', node => node.rank > 25 ? 0.5 : 1)
            .attr('tabindex', 0)
            .attr('role', 'button')
            .attr('aria-label', node => 'Rank #' + node.rank + ', ' + node.team_name +
                ', PPV ' + Number(node.points_per_voter).toFixed(2))
            .on('mouseenter focus', showTooltip)
            .on('mousemove', showTooltip)
            .on('mouseleave blur', hideTooltip)
            .on('click', showTooltip);
    }

    let resizeFrame;
    new ResizeObserver(() => {
        cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(render);
    }).observe(container);
    render();
}());
