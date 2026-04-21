import { Container, Group, Text } from '@mantine/core';
import { IconChartHistogram } from '@tabler/icons-react';
import { ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ColorSchemeSwitch } from './ColorSchemeSwitch.tsx';
import classes from './Header.module.css';

export function Header(): ReactNode {
  const location = useLocation();
  const navigate = useNavigate();

  const links = [
    { label: 'Results', path: '/' },
    { label: 'Run', path: '/run' },
    { label: 'Workshop', path: '/workshop' },
  ];

  return (
    <header className={classes.header}>
      <Container size="md" className={classes.inner}>
        <Text size="xl" fw={700}>
          <IconChartHistogram size={30} className={classes.icon} />
          Prosperity 4 MC
        </Text>

        <Group gap={4}>
          {links.map(link => (
            <a
              key={link.path}
              className={classes.link}
              data-active={location.pathname === link.path || undefined}
              onClick={e => { e.preventDefault(); navigate(link.path); }}
              href={link.path}
            >
              {link.label}
            </a>
          ))}
        </Group>

        <Group gap="sm">
          <ColorSchemeSwitch />
        </Group>
      </Container>
    </header>
  );
}
